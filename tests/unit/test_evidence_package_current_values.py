"""Synthetic-only packages, in-memory SQLite, and real temporary raw/hash chains."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.evidence_package import (
    EvidencePackage,
    EvidencePackageItem,
    EvidencePackageRun,
    EvidenceReference,
)
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingFieldComparison,
    MappingRuleSet,
)
from cloud_expert.evidence_packages import builder
from tests.unit.test_comparability_current_evidence import (
    NOW,
    Chain,
    _chain,
    raw_root,  # noqa: F401
)


@dataclass
class Case:
    candidate: MappingCandidate
    comparison: MappingFieldComparison
    source: Chain
    target: Chain


@pytest.fixture
def case(session: Session, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Case:
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(builder, "datetime", Clock)
    root: Path = request.getfixturevalue("raw_root")
    source = _chain(session, root, provider_code="synthetic_source")
    target = _chain(session, root, provider_code="synthetic_target")
    for chain in (source, target):
        chain.source.captured_at = chain.snapshot.captured_at = NOW - timedelta(hours=1)
    rule = MappingRuleSet(
        rule_set_code="synthetic_current_package",
        rule_set_version="synthetic-v1",
        mapping_level="sku",
        category="compute",
        market_mode="domestic",
        status="active",
    )
    session.add(rule)
    session.flush()
    candidate = MappingCandidate(
        rule_set_id=rule.id,
        mapping_level="sku",
        source_provider_id=source.product.provider_id,
        target_provider_id=target.product.provider_id,
        source_entity_type="sku",
        target_entity_type="sku",
        source_entity_id=source.sku.id,
        target_entity_id=target.sku.id,
        relationship_type="close_alternative",
        candidate_status="candidate",
        review_status="pending_review",
        blocking_reasons=[],
        conditions=[],
        explanation="Synthetic test case, not official product evidence or an approval.",
        generated_at=NOW,
    )
    session.add(candidate)
    session.flush()
    comparison = MappingFieldComparison(
        mapping_candidate_id=candidate.id,
        canonical_field_id=source.row.canonical_field_id,
        source_value_id=source.row.id,
        target_value_id=target.row.id,
        semantic_status="match",
        unit_status="match",
        scope_status="match",
        qualifier_status="match",
        evidence_status="match",
        comparison_status="match",
        freshness_status="fresh",
        created_at=NOW,
    )
    session.add(comparison)
    for chain in (source, target):
        session.add(
            MappingCandidateEvidence(
                mapping_candidate_id=candidate.id,
                evidence_id=chain.evidence.id,
                evidence_role="source_field" if chain is source else "target_field",
                created_at=NOW,
            )
        )
    session.commit()
    return Case(candidate, comparison, source, target)


def _latest(session: Session) -> EvidencePackage:
    package = session.scalars(select(EvidencePackage).order_by(EvidencePackage.id.desc())).first()
    assert package is not None
    return package


def _item(session: Session, package: EvidencePackage) -> EvidencePackageItem:
    return session.scalars(
        select(EvidencePackageItem).where(EvidencePackageItem.package_id == package.id)
    ).one()


def _counts(session: Session) -> tuple[int, ...]:
    return tuple(
        session.scalar(select(func.count()).select_from(model)) or 0
        for model in (EvidencePackage, EvidencePackageItem, EvidencePackageRun, EvidenceReference)
    )


def test_current_chain_is_complete_and_idempotent_but_not_approved(
    session: Session, case: Case
) -> None:
    result = builder.build_evidence_packages(session)
    package = _latest(session)
    item = _item(session, package)
    assert result.packages == result.items == 1
    assert result.references == 2
    assert package.evidence_completeness == Decimal("1.0000")
    assert package.customer_eligible is False
    assert item.source_value_id == case.source.row.id
    assert item.target_value_id == case.target.row.id
    assert item.source_reference_code and item.target_reference_code
    assert item.comparison_status == "match"
    counts = _counts(session)
    builder.build_evidence_packages(session)
    assert _counts(session) == counts
    assert (
        case.source.row.review_status == case.source.evidence.review_status == "machine_extracted"
    )
    assert case.source.source.authority_level == "unknown"
    assert package.package_version.startswith(builder.PACKAGE_VERSION)


@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize(
    "invalid",
    [
        "old_source",
        "old_snapshot",
        "tamper",
        "missing_raw",
        "future",
        "expired",
        "evidence_rejected",
        "value_rejected",
        "snapshotless",
        "hash_mismatch",
        "missing_value",
    ],
)
def test_invalidated_chain_creates_new_incomplete_package_and_preserves_history(
    session: Session, case: Case, side: str, invalid: str
) -> None:
    # Historical approval shape exists only in this synthetic in-memory fixture.
    case.candidate.candidate_status = "approved"
    case.candidate.review_status = "human_reviewed"
    session.commit()
    builder.build_evidence_packages(session)
    old = _latest(session)
    assert old.customer_eligible is True
    old_item = _item(session, old)
    old_data = {
        c.name: getattr(old, c.name) for c in old.__table__.columns if c.name != "superseded_by_id"
    }
    old_item_data = {c.name: getattr(old_item, c.name) for c in old_item.__table__.columns}
    old_refs = session.scalars(select(EvidenceReference).order_by(EvidenceReference.id)).all()
    ref_data = [{c.name: getattr(ref, c.name) for c in ref.__table__.columns} for ref in old_refs]
    chain = getattr(case, side)
    if invalid == "old_source":
        chain.source.is_current = False
    elif invalid == "old_snapshot":
        chain.snapshot.is_current = False
    elif invalid == "tamper":
        chain.path.write_bytes(b"x" * chain.path.stat().st_size)
    elif invalid == "missing_raw":
        chain.path.unlink()
    elif invalid == "future":
        chain.spec.valid_from = NOW + timedelta(seconds=1)
    elif invalid == "expired":
        chain.spec.valid_to = NOW
    elif invalid == "evidence_rejected":
        chain.evidence.review_status = "rejected"
    elif invalid == "value_rejected":
        chain.row.review_status = "rejected"
    elif invalid == "snapshotless":
        chain.evidence.snapshot_record_id = None
    elif invalid == "hash_mismatch":
        chain.snapshot.content_hash = "a" * 64
    else:
        setattr(case.comparison, f"{side}_value_id", None)
    session.commit()

    builder.build_evidence_packages(session)
    new = _latest(session)
    item = _item(session, new)
    assert new.id != old.id and new.content_hash != old.content_hash
    assert new.evidence_completeness == Decimal("0.0000")
    assert new.customer_eligible is False and new.output_level == "internal_raw"
    assert item.comparison_status == "insufficient_evidence"
    assert item.blocking_reason == "invalid_or_missing_current_normalized_evidence"
    for field in ("value_id", "evidence_id", "reference_code"):
        assert getattr(item, f"{side}_{field}") is None
        assert getattr(item, f"{'target' if side == 'source' else 'source'}_{field}") is not None
    assert old.superseded_by_id == new.id
    assert {key: getattr(old, key) for key in old_data} == old_data
    assert {key: getattr(old_item, key) for key in old_item_data} == old_item_data
    assert [
        {key: getattr(ref, key) for key in data}
        for ref, data in zip(old_refs, ref_data, strict=True)
    ] == ref_data
    counts = _counts(session)
    builder.build_evidence_packages(session)
    assert _counts(session) == counts


def test_invalid_values_never_create_new_references(session: Session, case: Case) -> None:
    case.source.snapshot.is_current = False
    case.target.path.write_bytes(b"synthetic corrupted content")
    session.commit()
    result = builder.build_evidence_packages(session)
    assert result.references == 0
    item = _item(session, _latest(session))
    assert item.source_value_id is item.target_value_id is None
    assert item.source_evidence_id is item.target_evidence_id is None
    assert item.source_reference_code is item.target_reference_code is None


def test_hash_depends_on_raw_content_even_when_both_mutations_are_invalid(
    session: Session, case: Case
) -> None:
    before = builder._content_hash(session, case.candidate, now=NOW)
    size = case.source.path.stat().st_size
    case.source.path.write_bytes(b"x" * size)
    first = builder._content_hash(session, case.candidate, now=NOW)
    case.source.path.write_bytes(b"y" * size)
    second = builder._content_hash(session, case.candidate, now=NOW)
    assert len({before, first, second}) == 3


def test_expiry_alone_changes_hash_and_completeness(session: Session, case: Case) -> None:
    case.source.spec.valid_to = NOW + timedelta(seconds=1)
    session.commit()
    before = builder._content_hash(session, case.candidate, now=NOW)
    after = builder._content_hash(session, case.candidate, now=NOW + timedelta(seconds=1))
    assert before != after
    assert builder._package_completeness(session, case.candidate, now=NOW) == 1
    assert (
        builder._package_completeness(session, case.candidate, now=NOW + timedelta(seconds=1)) == 0
    )


def test_restored_current_state_creates_successor_not_resurrected_history(
    session: Session, case: Case
) -> None:
    builder.build_evidence_packages(session)
    first = _latest(session)
    case.source.snapshot.is_current = False
    session.commit()
    builder.build_evidence_packages(session)
    second = _latest(session)
    case.source.snapshot.is_current = True
    session.commit()
    builder.build_evidence_packages(session)
    third = _latest(session)
    assert first.id < second.id < third.id
    assert first.superseded_by_id == second.id
    assert second.superseded_by_id == third.id
    assert third.superseded_by_id is None
    assert third.evidence_completeness == first.evidence_completeness == 1
    counts = _counts(session)
    builder.build_evidence_packages(session)
    assert _counts(session) == counts


def test_product_category_approval_semantics_unchanged(
    session: Session, case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.delete(case.comparison)
    session.flush()
    case.candidate.mapping_level = "product"
    case.source.snapshot.is_current = False
    case.target.snapshot.is_current = False
    monkeypatch.setattr(builder, "mapping_approval", lambda *_: None)
    assert builder._package_completeness(session, case.candidate, now=NOW) == 0
    monkeypatch.setattr(builder, "mapping_approval", lambda *_: {"synthetic_test_only": True})
    assert builder._package_completeness(session, case.candidate, now=NOW) == 1
    case.candidate.mapping_level = "sku"
    assert builder._package_completeness(session, case.candidate, now=NOW) == 0
