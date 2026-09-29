from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.source import Evidence
from cloud_expert.evidence_packages.builder import build_evidence_packages
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.mapping.pipeline import _first_product_evidence
from cloud_expert.mapping.revision import revise_product_mapping
from cloud_expert.model_review import approvals, pilot
from cloud_expert.model_review.migration import migrate_precheck
from cloud_expert.parsing.pipeline import parse_source_entry
from tests.unit.test_aliyun_parsing_pipeline import _aliyun_fixture_entry
from tests.unit.test_huawei_parsing_pipeline import _fixture_entry
from tests.unit.test_synthetic_business_chain import synthetic_chain  # noqa: F401


@pytest.fixture
def revision_input(request, tmp_path, monkeypatch):
    session = request.getfixturevalue("synthetic_chain")
    monkeypatch.setattr(pilot, "RAW_ROOT", (tmp_path / "raw").resolve())
    monkeypatch.setattr(pilot, "OFFICIAL_HOSTS", ("example.invalid",))
    monkeypatch.setattr(approvals, "RAW_ROOT", (tmp_path / "raw").resolve())
    monkeypatch.setattr(approvals, "OFFICIAL_HOSTS", ("example.invalid",))
    for name, factory in (("huawei", _fixture_entry), ("aliyun", _aliyun_fixture_entry)):
        fixture = tmp_path / f"{name}_definition.html"
        fixture.write_text(
            "<html><body><p>弹性云服务器 ECS 是一个用于软件回归测试的合成计算服务，"
            "此说明仅用于验证产品级描述的证据链路，不代表任何真实云产品的配置和性能。</p></body></html>",
            encoding="utf-8",
        )
        entry = factory(
            fixture,
            source_id=f"synthetic_{name}_ecs_definition",
            product_code="ecs",
            source_type="documentation",
        )
        store = SnapshotStore(tmp_path / "raw")
        SourceFetcher(snapshot_store=store).fetch(entry, session=session)
        parse_source_entry(session, entry, store)
    old = next(
        candidate
        for candidate in session.scalars(select(MappingCandidate))
        if candidate.mapping_level == "product"
        and candidate.target_provider.code == "aliyun"
        and session.get(Product, candidate.source_entity_id).code == "ecs"
    )
    build_evidence_packages(session, "product")
    run = ModelReviewRun(
        run_code="synthetic_old_review",
        policy_version="test",
        reviewer_model="deterministic_evidence_precheck",
        input_fingerprint="a" * 64,
        reviewed_at=datetime.now(UTC),
        summary_json={},
    )
    session.add(run)
    session.flush()
    session.add(
        ModelReviewFinding(
            run_id=run.id,
            subject_type="mapping_candidate",
            subject_id=old.id,
            verdict="requires_dual_model_review",
            reason_code="synthetic",
            rationale="Synthetic only",
            evidence_ids=[link.evidence_id for link in old.evidence_links],
            input_hash="b" * 64,
        )
    )
    session.flush()
    migrate_precheck(session, run.run_code, apply=True)
    return session, old


def test_revision_preserves_history_and_validates_raw_files(revision_input):
    session, old = revision_input
    old_package = session.scalar(
        select(EvidencePackage).where(EvidencePackage.mapping_candidate_id == old.id)
    )
    old_assignment = session.scalar(
        select(ModelReviewAssignment).where(ModelReviewAssignment.target_id == old.id)
    )
    result = revise_product_mapping(session, old.id)
    new = session.get(MappingCandidate, result["new_id"])
    assert new.id != old.id and old.candidate_status == "superseded"
    assert old.superseded_by_id == new.id
    assert old_package.superseded_by_id == result["package_id"]
    assert old_assignment.review_state == "superseded"
    assert (
        len(
            list(
                session.scalars(
                    select(ModelReviewAuditEvent).where(
                        ModelReviewAuditEvent.assignment_id == old_assignment.id
                    )
                )
            )
        )
        == 2
    )
    assert approvals.mapping_evidence_valid(session, new)
    payload = pilot.mapping_review_input(session, result["precheck_run_code"], new.id)
    assert {row["evidence_id"] for row in payload["evidence"]} == set(result["evidence_ids"])
    assert len(payload["evidence"]) == 2
    assert revise_product_mapping(session, old.id)["status"] == "already_revised"
    assert new.review_status == "pending_review"
    assert new.candidate_status == "candidate"


@pytest.mark.parametrize(
    "fault", ["raw_tamper", "nonofficial", "snapshot_hash", "unsafe_path", "missing_raw"]
)
def test_bad_provenance_does_not_retire_old_mapping(revision_input, fault):
    session, old = revision_input
    evidence = session.get(Evidence, _first_product_evidence(session, old.source_entity_id))
    from cloud_expert.database.models.snapshot import SnapshotRecord

    snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
    raw = pilot.RAW_ROOT / snapshot.storage_path
    if fault == "raw_tamper":
        raw.write_bytes(b"synthetic tampering")
    elif fault == "nonofficial":
        evidence.source_document.url = "https://untrusted.invalid/source"
    elif fault == "snapshot_hash":
        snapshot.content_hash = "0" * 64
    elif fault == "unsafe_path":
        snapshot.storage_path = "../outside.bin"
    elif fault == "missing_raw":
        snapshot.storage_path = "missing.bin"
    session.commit()
    assert not approvals.mapping_evidence_valid(session, old)
    with pytest.raises(ValueError):
        revise_product_mapping(session, old.id)
    session.rollback()
    assert session.get(MappingCandidate, old.id).candidate_status != "superseded"


def test_terminal_and_cross_market_mappings_are_not_revised(revision_input):
    session, old = revision_input
    old.candidate_status = "approved"
    with pytest.raises(ValueError, match="terminal"):
        revise_product_mapping(session, old.id)
    old.candidate_status = "candidate"
    target = session.get(Product, old.target_entity_id)
    target.market_mode = "international"
    with pytest.raises(ValueError, match="same-market"):
        revise_product_mapping(session, old.id)
    with pytest.raises(ValueError, match="existing product"):
        revise_product_mapping(session, -1)
