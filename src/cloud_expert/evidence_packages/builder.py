from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from cloud_expert.config.settings import get_settings
from cloud_expert.database.enums import (
    EvidenceOutputLevel,
    EvidencePackageRunStatus,
    EvidencePackageType,
    FreshnessStatus,
    MappingCandidateStatus,
    MappingLevel,
    ReviewStatus,
)
from cloud_expert.database.models.evidence_package import (
    EvidencePackage,
    EvidencePackageItem,
    EvidencePackageRun,
)
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingFieldComparison,
)
from cloud_expert.evidence_packages.references import ensure_reference

PACKAGE_VERSION = "2026.07.week08.v1"


@dataclass
class EvidencePackageBuildResult:
    candidates: int
    packages: int
    items: int
    references: int
    missing_evidence: int
    stale: int
    customer_eligible: int

    def as_dict(self) -> dict[str, int]:
        return {
            "candidates": self.candidates,
            "packages": self.packages,
            "items": self.items,
            "references": self.references,
            "missing_evidence": self.missing_evidence,
            "stale": self.stale,
            "customer_eligible": self.customer_eligible,
        }


def make_session(database_url: str | None = None) -> Session:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def build_evidence_packages(
    session: Session, mapping_level: str | None = None
) -> EvidencePackageBuildResult:
    now = datetime.now(UTC)
    query = select(MappingCandidate).order_by(MappingCandidate.id)
    if mapping_level is not None:
        query = query.where(MappingCandidate.mapping_level == mapping_level)
    candidates = list(session.scalars(query).all())
    run = EvidencePackageRun(
        run_code=f"EPR-{PACKAGE_VERSION}-{mapping_level or 'all'}",
        package_type=EvidencePackageType.MAPPING_REVIEW.value,
        started_at=now,
        status=EvidencePackageRunStatus.PARTIAL.value,
        candidate_count=len(candidates),
        package_count=0,
        item_count=0,
        conflict_count=0,
        missing_evidence_count=0,
        stale_count=0,
        error_count=0,
        generator_version=PACKAGE_VERSION,
    )
    existing_run = session.scalar(
        select(EvidencePackageRun).where(EvidencePackageRun.run_code == run.run_code)
    )
    if existing_run is None:
        session.add(run)
        session.flush()
    else:
        run = existing_run

    for candidate in candidates:
        package = _ensure_package(session, candidate, now)
        _ensure_package_items(session, package, candidate, now)

    run.completed_at = now
    run.status = EvidencePackageRunStatus.SUCCEEDED.value
    run.package_count = session.scalar(select(func.count()).select_from(EvidencePackage)) or 0
    run.item_count = session.scalar(select(func.count()).select_from(EvidencePackageItem)) or 0
    run.missing_evidence_count = _missing_evidence_count(session)
    run.stale_count = _stale_count(session)
    session.commit()
    return EvidencePackageBuildResult(
        candidates=len(candidates),
        packages=session.scalar(select(func.count()).select_from(EvidencePackage)) or 0,
        items=session.scalar(select(func.count()).select_from(EvidencePackageItem)) or 0,
        references=_reference_count(session),
        missing_evidence=run.missing_evidence_count,
        stale=run.stale_count,
        customer_eligible=session.scalar(
            select(func.count())
            .select_from(EvidencePackage)
            .where(EvidencePackage.customer_eligible.is_(True))
        )
        or 0,
    )


def _customer_eligible_mapping(candidate: MappingCandidate) -> bool:
    return (
        candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value
        and candidate.rule_set.market_mode != "cross_market"
        and candidate.candidate_status == MappingCandidateStatus.APPROVED.value
        and not candidate.blocking_reasons
    )


def _ensure_package(
    session: Session, candidate: MappingCandidate, now: datetime
) -> EvidencePackage:
    code = _package_code(candidate)
    existing = session.scalar(
        select(EvidencePackage).where(
            EvidencePackage.package_code == code,
            EvidencePackage.package_version == PACKAGE_VERSION,
        )
    )
    content_hash = _content_hash(candidate)
    package_type = _package_type(candidate.mapping_level)
    eligible = _customer_eligible_mapping(candidate)
    values: dict[str, Any] = {
        "package_type": package_type,
        "market_mode": candidate.rule_set.market_mode,
        "source_entity_type": candidate.source_entity_type,
        "source_entity_id": candidate.source_entity_id,
        "target_entity_type": candidate.target_entity_type,
        "target_entity_id": candidate.target_entity_id,
        "mapping_candidate_id": candidate.id,
        "rule_set_version": candidate.rule_set.rule_set_version,
        "generated_at": now,
        "freshness_status": FreshnessStatus.UNKNOWN.value,
        "evidence_completeness": Decimal("1.0000"),
        "review_status": candidate.review_status,
        "output_level": (
            EvidenceOutputLevel.CUSTOMER_ELIGIBLE.value
            if eligible
            else EvidenceOutputLevel.INTERNAL_RAW.value
        ),
        "customer_eligible": eligible,
        "content_hash": content_hash,
        "created_at": now,
    }
    if existing is None:
        existing = EvidencePackage(
            package_code=code,
            package_version=PACKAGE_VERSION,
            **values,
        )
        session.add(existing)
        session.flush()
    else:
        for key, value in values.items():
            setattr(existing, key, value)
    return existing


def _ensure_package_items(
    session: Session,
    package: EvidencePackage,
    candidate: MappingCandidate,
    now: datetime,
) -> None:
    comparisons = list(
        session.scalars(
            select(MappingFieldComparison)
            .where(MappingFieldComparison.mapping_candidate_id == candidate.id)
            .order_by(MappingFieldComparison.id)
        ).all()
    )
    if comparisons:
        for index, comparison in enumerate(comparisons, start=1):
            source_ref = (
                ensure_reference(session, comparison.source_value.evidence_id, now)
                if comparison.source_value is not None
                else None
            )
            target_ref = (
                ensure_reference(session, comparison.target_value.evidence_id, now)
                if comparison.target_value is not None
                else None
            )
            _upsert_item(
                session=session,
                package=package,
                display_order=index,
                canonical_field_id=comparison.canonical_field_id,
                source_value_id=comparison.source_value_id,
                target_value_id=comparison.target_value_id,
                source_evidence_id=(
                    comparison.source_value.evidence_id
                    if comparison.source_value is not None
                    else None
                ),
                target_evidence_id=(
                    comparison.target_value.evidence_id
                    if comparison.target_value is not None
                    else None
                ),
                source_reference_code=source_ref.reference_code if source_ref is not None else None,
                target_reference_code=target_ref.reference_code if target_ref is not None else None,
                comparison_status=comparison.comparison_status,
                matched_status=comparison.semantic_status,
                scope_status=comparison.scope_status,
                qualifier_status=comparison.qualifier_status,
                freshness_status=FreshnessStatus.UNKNOWN.value,
                conflict_status="none",
                blocking_reason=comparison.blocking_reason,
                now=now,
            )
        return

    links = list(
        session.scalars(
            select(MappingCandidateEvidence)
            .where(MappingCandidateEvidence.mapping_candidate_id == candidate.id)
            .order_by(MappingCandidateEvidence.id)
        ).all()
    )
    source_link = links[0] if links else None
    target_link = links[1] if len(links) > 1 else None
    source_ref = ensure_reference(session, source_link.evidence_id, now) if source_link else None
    target_ref = ensure_reference(session, target_link.evidence_id, now) if target_link else None
    _upsert_item(
        session=session,
        package=package,
        display_order=1,
        canonical_field_id=None,
        source_value_id=None,
        target_value_id=None,
        source_evidence_id=source_link.evidence_id if source_link else None,
        target_evidence_id=target_link.evidence_id if target_link else None,
        source_reference_code=source_ref.reference_code if source_ref else None,
        target_reference_code=target_ref.reference_code if target_ref else None,
        comparison_status=candidate.candidate_status,
        matched_status=candidate.relationship_type,
        scope_status="not_evaluated",
        qualifier_status="not_evaluated",
        freshness_status=FreshnessStatus.UNKNOWN.value,
        conflict_status="none",
        blocking_reason=";".join(candidate.blocking_reasons or []) or None,
        now=now,
    )


def _upsert_item(
    *,
    session: Session,
    package: EvidencePackage,
    display_order: int,
    canonical_field_id: int | None,
    source_value_id: int | None,
    target_value_id: int | None,
    source_evidence_id: int | None,
    target_evidence_id: int | None,
    source_reference_code: str | None,
    target_reference_code: str | None,
    comparison_status: str,
    matched_status: str,
    scope_status: str,
    qualifier_status: str,
    freshness_status: str,
    conflict_status: str,
    blocking_reason: str | None,
    now: datetime,
) -> None:
    field_condition = (
        EvidencePackageItem.canonical_field_id.is_(None)
        if canonical_field_id is None
        else EvidencePackageItem.canonical_field_id == canonical_field_id
    )
    source_condition = (
        EvidencePackageItem.source_value_id.is_(None)
        if source_value_id is None
        else EvidencePackageItem.source_value_id == source_value_id
    )
    target_condition = (
        EvidencePackageItem.target_value_id.is_(None)
        if target_value_id is None
        else EvidencePackageItem.target_value_id == target_value_id
    )
    existing = session.scalar(
        select(EvidencePackageItem).where(
            EvidencePackageItem.package_id == package.id,
            field_condition,
            source_condition,
            target_condition,
            EvidencePackageItem.display_order == display_order,
        )
    )
    values = {
        "source_evidence_id": source_evidence_id,
        "target_evidence_id": target_evidence_id,
        "source_reference_code": source_reference_code,
        "target_reference_code": target_reference_code,
        "comparison_status": comparison_status,
        "matched_status": matched_status,
        "scope_status": scope_status,
        "qualifier_status": qualifier_status,
        "freshness_status": freshness_status,
        "conflict_status": conflict_status,
        "blocking_reason": blocking_reason,
        "created_at": now,
    }
    if existing is None:
        session.add(
            EvidencePackageItem(
                package_id=package.id,
                canonical_field_id=canonical_field_id,
                source_value_id=source_value_id,
                target_value_id=target_value_id,
                display_order=display_order,
                **values,
            )
        )
    else:
        for key, value in values.items():
            if key != "created_at":
                setattr(existing, key, value)


def _package_type(level: str) -> str:
    return {
        MappingLevel.PRODUCT.value: EvidencePackageType.PRODUCT_COMPARISON.value,
        MappingLevel.PRODUCT_FAMILY.value: EvidencePackageType.PRODUCT_FAMILY_COMPARISON.value,
        MappingLevel.SKU.value: EvidencePackageType.SKU_COMPARISON.value,
        MappingLevel.SERVICE_TIER.value: EvidencePackageType.SERVICE_TIER_COMPARISON.value,
    }.get(level, EvidencePackageType.MAPPING_REVIEW.value)


def _package_code(candidate: MappingCandidate) -> str:
    basis = (
        f"{candidate.rule_set.rule_set_version}|{candidate.mapping_level}|"
        f"{candidate.source_entity_type}:{candidate.source_entity_id}|"
        f"{candidate.target_entity_type}:{candidate.target_entity_id}"
    )
    return f"EP-{candidate.mapping_level.upper()}-{sha256(basis.encode('utf-8')).hexdigest()[:12].upper()}"


def _content_hash(candidate: MappingCandidate) -> str:
    payload = {
        "candidate_id": candidate.id,
        "rule_set_version": candidate.rule_set.rule_set_version,
        "mapping_level": candidate.mapping_level,
        "source": [candidate.source_entity_type, candidate.source_entity_id],
        "target": [candidate.target_entity_type, candidate.target_entity_id],
        "relationship_type": candidate.relationship_type,
        "candidate_status": candidate.candidate_status,
    }
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _missing_evidence_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(EvidencePackageItem)
            .where(
                EvidencePackageItem.source_evidence_id.is_(None)
                | EvidencePackageItem.target_evidence_id.is_(None)
            )
        )
        or 0
    )


def _stale_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(EvidencePackageItem)
            .where(EvidencePackageItem.freshness_status == FreshnessStatus.STALE.value)
        )
        or 0
    )


def _reference_count(session: Session) -> int:
    from cloud_expert.database.models.evidence_package import EvidenceReference

    return session.scalar(select(func.count()).select_from(EvidenceReference)) or 0
