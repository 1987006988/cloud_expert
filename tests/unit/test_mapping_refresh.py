"""Synthetic SQLite refresh preparation; no model calls or business database access."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import inspect, select

from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingRuleSet,
)
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.mapping import revision
from cloud_expert.mapping.pipeline import _first_product_evidence
from cloud_expert.model_review import approvals, pilot
from cloud_expert.parsing.pipeline import parse_source_entry
from tests.unit import test_mapping_revision as revision_tests

revision_input = revision_tests.revision_input
synthetic_chain = revision_tests.synthetic_chain

HISTORY_MODELS = (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingRuleSet,
    EvidencePackage,
    ModelReviewAssignment,
    ModelReviewAuditEvent,
    ModelReviewFinding,
    ModelReviewRun,
)


def _rows(session: Any) -> dict[type, dict[int, dict[str, Any]]]:
    return {
        model: {
            row.id: deepcopy({col.key: getattr(row, col.key) for col in inspect(model).columns})
            for row in session.scalars(select(model))
        }
        for model in HISTORY_MODELS
    }


def _assert_history_unchanged(fixture: Any) -> None:
    current = _rows(fixture.session)
    for model, rows in fixture.original.items():
        for row_id, columns in rows.items():
            assert current[model][row_id] == columns
    old = fixture.session.get(MappingCandidate, fixture.old_id)
    assert old.candidate_status == "approved"
    assert old.superseded_by_id is None
    assert approvals.mapping_subject_hash(old) == fixture.subject_hash


@pytest.fixture
def refresh_input(revision_input: Any, tmp_path: Path) -> Any:
    session, old = revision_input
    store = revision_tests.SnapshotStore(tmp_path / "raw")
    for name, product_id, factory in (
        ("huawei", old.source_entity_id, revision_tests._fixture_entry),
        ("aliyun", old.target_entity_id, revision_tests._aliyun_fixture_entry),
    ):
        raw_file = tmp_path / f"synthetic_refreshed_{name}.html"
        original = (tmp_path / f"{name}_definition.html").read_text(encoding="utf-8")
        raw_file.write_text(
            original.replace("</p>", f" SYNTHETIC refreshed {name} definition.</p>"),
            encoding="utf-8",
        )
        entry = factory(
            raw_file,
            source_id=f"synthetic_refresh_{name}",
            product_code="ecs",
            source_type="documentation",
        )
        revision_tests.SourceFetcher(snapshot_store=store).fetch(entry, session=session)
        parse_source_entry(session, entry, store)
        parsed = session.scalar(
            select(ParsedFieldCandidate)
            .join(ParsingRun)
            .where(
                ParsingRun.source_id == entry.source_id,
                ParsedFieldCandidate.field_code == "product.description",
            )
            .order_by(ParsedFieldCandidate.id.desc())
        )
        assert parsed is not None and parsed.evidence_id is not None
        session.get(Product, product_id).description = parsed.raw_value
    session.flush()
    old.candidate_status = "approved"
    assignment = session.scalar(
        select(ModelReviewAssignment)
        .where(
            ModelReviewAssignment.target_type == "mapping_candidate",
            ModelReviewAssignment.target_id == old.id,
        )
        .order_by(ModelReviewAssignment.id.desc())
    )
    assert assignment is not None
    assignment.review_state = "model_approved_with_conditions"
    session.add(
        ModelReviewAuditEvent(
            assignment_id=assignment.id,
            event_code="synthetic_refresh_prior_approval",
            previous_status="pending_model_review",
            new_status="model_approved_with_conditions",
            source="independent_model_review",
            model_id="synthetic-model-no-call",
            reason="SYNTHETIC historical approval fixture, not a real model review",
            affected_records=[
                {
                    "target_id": old.id,
                    "subject_hash": approvals.mapping_subject_hash(old),
                    "approved_scope": "product_category_only",
                    "conditions_enforced": True,
                }
            ],
            downstream_rebuild_required=False,
            timestamp=datetime.now(UTC),
        )
    )
    session.commit()
    fresh_ids = [
        _first_product_evidence(session, product_id)
        for product_id in (old.source_entity_id, old.target_entity_id)
    ]
    assert None not in fresh_ids and len(set(fresh_ids)) == 2
    assert not set(fresh_ids) & {link.evidence_id for link in old.evidence_links}
    return SimpleNamespace(
        session=session,
        old_id=old.id,
        subject_hash=approvals.mapping_subject_hash(old),
        fresh_ids=set(fresh_ids),
        original=_rows(session),
    )


def _prepare(fixture: Any, **kwargs: Any) -> dict[str, Any]:
    return revision.prepare_product_mapping_refresh(
        fixture.session,
        fixture.old_id,
        expected_subject_sha256=kwargs.get("expected_subject_sha256", fixture.subject_hash),
    )


def test_refresh_preserves_committed_approval_and_all_history(refresh_input: Any) -> None:
    f = refresh_input
    result = _prepare(f)
    assert result["status"] == "prepared"
    assert result["old_id"] == f.old_id and result["new_id"] != f.old_id
    assert result["prior_approval_preserved"] is True
    assert result["customer_eligible"] is False
    child = f.session.get(MappingCandidate, result["new_id"])
    assert child.candidate_status == "candidate"
    assert child.review_status == "pending_review"
    assert child.superseded_by_id is None
    assert set(result["evidence_ids"]) == f.fresh_ids
    assert {link.evidence_id for link in child.evidence_links} == f.fresh_ids
    assignment = f.session.get(ModelReviewAssignment, result["assignment_id"])
    assert assignment.review_state == "pending_model_review"
    events = list(
        f.session.scalars(
            select(ModelReviewAuditEvent).where(
                ModelReviewAuditEvent.assignment_id == assignment.id
            )
        )
    )
    assert events and all(event.model_id is None for event in events)
    assert all(event.new_status == "pending_model_review" for event in events)
    assert approvals.mapping_approval(f.session, child) is None
    assert approvals.mapping_evidence_valid(f.session, child)
    _assert_history_unchanged(f)
    f.session.commit()
    _assert_history_unchanged(f)


def test_repeated_same_committed_inputs_return_same_pending_child(refresh_input: Any) -> None:
    f = refresh_input
    first = _prepare(f)
    f.session.commit()
    before = _rows(f.session)
    second = _prepare(f)
    assert second["status"] == "already_prepared"
    assert second["new_id"] == first["new_id"]
    assert second["precheck_run_code"] == first["precheck_run_code"]
    assert second["customer_eligible"] is False
    assert _rows(f.session) == before
    _assert_history_unchanged(f)


def test_preparation_does_not_commit_callers_transaction(refresh_input: Any) -> None:
    f = refresh_input
    result = _prepare(f)
    new_id = result["new_id"]
    f.session.rollback()
    assert f.session.get(MappingCandidate, new_id) is None
    assert _rows(f.session) == f.original
    _assert_history_unchanged(f)


def test_failed_final_validation_can_be_rolled_back_atomically(
    refresh_input: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = refresh_input

    def reject(*args: Any, **kwargs: Any) -> None:
        raise ValueError("SYNTHETIC final provenance validation failure")

    monkeypatch.setattr(revision, "mapping_review_input", reject)
    with pytest.raises(ValueError, match="SYNTHETIC final provenance"):
        _prepare(f)
    f.session.rollback()
    assert _rows(f.session) == f.original
    _assert_history_unchanged(f)


def test_refresh_rejects_the_same_evidence_already_linked_to_old_mapping(
    refresh_input: Any,
) -> None:
    f = refresh_input
    old = f.session.get(MappingCandidate, f.old_id)
    for link in list(old.evidence_links):
        f.session.delete(link)
    for evidence_id in f.fresh_ids:
        f.session.add(
            MappingCandidateEvidence(
                mapping_candidate_id=old.id,
                evidence_id=evidence_id,
                evidence_role="category_positioning",
                created_at=datetime.now(UTC),
            )
        )
    f.session.commit()
    f.subject_hash = approvals.mapping_subject_hash(old)
    before = _rows(f.session)
    with pytest.raises(ValueError):
        _prepare(f)
    assert _rows(f.session) == before


@pytest.mark.parametrize("expected", ["0" * 64, "", None, True, "SYNTHETIC not a hash"])
def test_expected_subject_hash_fails_closed_without_creating_child(
    refresh_input: Any,
    expected: Any,
) -> None:
    with pytest.raises(ValueError):
        _prepare(refresh_input, expected_subject_sha256=expected)
    assert _rows(refresh_input.session) == refresh_input.original


def test_dirty_session_is_not_silently_flushed(refresh_input: Any) -> None:
    f = refresh_input
    old = f.session.get(MappingCandidate, f.old_id)
    old.explanation = "SYNTHETIC unsaved change"
    with pytest.raises(ValueError, match="clean session"):
        _prepare(f)
    assert old.explanation == "SYNTHETIC unsaved change"
    f.session.rollback()
    _assert_history_unchanged(f)


def test_changed_committed_parent_cannot_use_prior_expected_hash(refresh_input: Any) -> None:
    f = refresh_input
    old = f.session.get(MappingCandidate, f.old_id)
    old.conditions = ["SYNTHETIC changed approved scope"]
    f.session.commit()
    before = _rows(f.session)
    with pytest.raises(ValueError, match="subject changed"):
        _prepare(f)
    assert _rows(f.session) == before


@pytest.mark.parametrize("status", ["candidate", "rejected", "corrected", "superseded"])
def test_refresh_requires_old_approved_candidate(refresh_input: Any, status: str) -> None:
    f = refresh_input
    old = f.session.get(MappingCandidate, f.old_id)
    old.candidate_status = status
    f.session.commit()
    before = _rows(f.session)
    with pytest.raises(ValueError):
        _prepare(f)
    assert _rows(f.session) == before


@pytest.mark.parametrize(
    "fault", ["stale", "not_current", "future", "raw_tamper", "missing_raw", "cross_market"]
)
def test_invalid_fresh_evidence_never_retires_old_approval(refresh_input: Any, fault: str) -> None:
    f = refresh_input
    evidence = f.session.get(Evidence, min(f.fresh_ids))
    if fault == "stale":
        evidence.source_document.captured_at = datetime.now(UTC) - timedelta(days=400)
    elif fault == "not_current":
        evidence.source_document.is_current = False
    elif fault == "future":
        evidence.source_document.captured_at = datetime.now(UTC) + timedelta(days=2)
    elif fault == "raw_tamper":
        snapshot = f.session.get(SnapshotRecord, evidence.snapshot_record_id)
        (pilot.RAW_ROOT / snapshot.storage_path).write_bytes(b"SYNTHETIC tamper")
    elif fault == "missing_raw":
        f.session.get(
            SnapshotRecord, evidence.snapshot_record_id
        ).storage_path = "synthetic_missing.bin"
    else:
        old = f.session.get(MappingCandidate, f.old_id)
        f.session.get(Product, old.target_entity_id).market_mode = "international"
    f.session.commit()
    with pytest.raises(ValueError):
        _prepare(f)
    f.session.rollback()
    _assert_history_unchanged(f)


@pytest.mark.parametrize(
    "mutation",
    [
        "scope",
        "status",
        "review_status",
        "blocker",
        "explanation",
        "assignment",
        "event",
        "missing_assignment",
        "raw_tamper",
    ],
)
def test_idempotent_retry_cannot_accept_changed_child_or_provenance(
    refresh_input: Any,
    mutation: str,
) -> None:
    f = refresh_input
    first = _prepare(f)
    f.session.commit()
    child = f.session.get(MappingCandidate, first["new_id"])
    assignment = f.session.get(ModelReviewAssignment, first["assignment_id"])
    if mutation == "scope":
        child.conditions = ["SYNTHETIC SKU equivalence claimed"]
    elif mutation == "status":
        child.candidate_status = "approved"
    elif mutation == "review_status":
        child.review_status = "rejected"
    elif mutation == "blocker":
        child.blocking_reasons = ["SYNTHETIC blocker"]
    elif mutation == "explanation":
        child.explanation = "SYNTHETIC changed subject"
    elif mutation == "assignment":
        assignment.review_state = "model_approved"
    elif mutation == "event":
        event = f.session.scalar(
            select(ModelReviewAuditEvent).where(
                ModelReviewAuditEvent.assignment_id == assignment.id
            )
        )
        event.reason = "SYNTHETIC changed audit"
    elif mutation == "missing_assignment":
        for event in f.session.scalars(
            select(ModelReviewAuditEvent).where(
                ModelReviewAuditEvent.assignment_id == assignment.id
            )
        ):
            f.session.delete(event)
        f.session.delete(assignment)
    else:
        evidence = f.session.get(Evidence, min(f.fresh_ids))
        snapshot = f.session.get(SnapshotRecord, evidence.snapshot_record_id)
        (pilot.RAW_ROOT / snapshot.storage_path).write_bytes(b"SYNTHETIC changed raw")
    f.session.commit()
    with pytest.raises(ValueError):
        _prepare(f)
    f.session.rollback()
    _assert_history_unchanged(f)
