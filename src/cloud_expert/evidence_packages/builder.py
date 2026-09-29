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
from cloud_expert.database.models.canonical import NormalizedSpecification
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
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.evidence_packages.references import ensure_reference, freshness_for
from cloud_expert.model_review.approvals import mapping_approval
from cloud_expert.normalization.evidence_validity import HashCache, normalized_evidence_valid

PACKAGE_VERSION = "2026.09.current-evidence.v4"


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
    query = (
        select(MappingCandidate)
        .where(
            MappingCandidate.candidate_status.not_in(
                [MappingCandidateStatus.REJECTED.value, MappingCandidateStatus.SUPERSEDED.value]
            )
        )
        .order_by(MappingCandidate.id)
    )
    if mapping_level is not None:
        query = query.where(MappingCandidate.mapping_level == mapping_level)
    candidates = list(session.scalars(query).all())
    candidate_hashes = {
        candidate.id: _content_hash(session, candidate, now=now) for candidate in candidates
    }
    run_fingerprint = sha256(
        json.dumps(candidate_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    run = EvidencePackageRun(
        run_code=f"EPR-{PACKAGE_VERSION}-{mapping_level or 'all'}-{run_fingerprint}",
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
    new_run = existing_run is None
    if existing_run is None:
        session.add(run)
        session.flush()
    else:
        run = existing_run

    for candidate in candidates:
        package, created = _ensure_package(session, candidate, now, candidate_hashes[candidate.id])
        if created:
            _ensure_package_items(session, package, candidate, now)

    _link_superseded_mapping_packages(session)

    if new_run:
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


def _link_superseded_mapping_packages(session: Session) -> None:
    for old_candidate in session.scalars(
        select(MappingCandidate).where(MappingCandidate.superseded_by_id.is_not(None))
    ):
        replacement = session.scalar(
            select(EvidencePackage)
            .where(
                EvidencePackage.mapping_candidate_id == old_candidate.superseded_by_id,
                EvidencePackage.superseded_by_id.is_(None),
            )
            .order_by(EvidencePackage.generated_at.desc(), EvidencePackage.id.desc())
        )
        if replacement is None:
            continue
        previous = session.scalar(
            select(EvidencePackage)
            .where(
                EvidencePackage.mapping_candidate_id == old_candidate.id,
                EvidencePackage.superseded_by_id.is_(None),
            )
            .order_by(EvidencePackage.generated_at.desc(), EvidencePackage.id.desc())
        )
        if previous is not None:
            previous.superseded_by_id = replacement.id


def _package_completeness(
    session: Session, candidate: MappingCandidate, *, now: datetime | None = None
) -> Decimal:
    at = now or datetime.now(UTC)
    hash_cache: HashCache = {}
    comparisons = session.scalars(
        select(MappingFieldComparison).where(
            MappingFieldComparison.mapping_candidate_id == candidate.id
        )
    ).all()
    if not comparisons:
        if candidate.mapping_level == MappingLevel.PRODUCT.value and mapping_approval(
            session, candidate
        ):
            return Decimal("1.0000")
        return Decimal("0.0000")
    usable = 0
    for comparison in comparisons:
        source = comparison.source_value
        target = comparison.target_value
        if (
            source is not None
            and target is not None
            and normalized_evidence_valid(session, source, hash_cache=hash_cache, now=at)
            and normalized_evidence_valid(session, target, hash_cache=hash_cache, now=at)
            and comparison.comparison_status in {"match", "close"}
            and comparison.scope_status == "match"
            and comparison.qualifier_status == "match"
            and comparison.evidence_status == "match"
        ):
            usable += 1
    return (Decimal(usable) / Decimal(len(comparisons))).quantize(Decimal("0.0001"))


def _customer_eligible_mapping(candidate: MappingCandidate, session: Session | None = None) -> bool:
    return (
        candidate.rule_set.market_mode in {"domestic", "international"}
        and candidate.candidate_status == MappingCandidateStatus.APPROVED.value
        and (
            candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value
            or (session is not None and mapping_approval(session, candidate) is not None)
        )
        and not candidate.blocking_reasons
    )


def _mapping_freshness(candidate: MappingCandidate, now: datetime) -> str:
    states = {
        freshness_for(link.evidence.source_document, now) for link in candidate.evidence_links
    }
    if not states:
        return FreshnessStatus.UNKNOWN.value
    for status in ("stale", "unknown", "historical", "due_soon"):
        if status in states:
            return status
    return FreshnessStatus.FRESH.value


def _ensure_package(
    session: Session, candidate: MappingCandidate, now: datetime, content_hash: str
) -> tuple[EvidencePackage, bool]:
    code = _package_code(candidate)
    existing = session.scalar(
        select(EvidencePackage).where(
            EvidencePackage.package_code == code,
            EvidencePackage.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, False
    package_type = _package_type(candidate.mapping_level)
    completeness = _package_completeness(session, candidate, now=now)
    freshness_status = _mapping_freshness(candidate, now)
    eligible = (
        _customer_eligible_mapping(candidate, session)
        and freshness_status == FreshnessStatus.FRESH.value
        and completeness == Decimal("1.0000")
    )
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
        "freshness_status": freshness_status,
        "evidence_completeness": completeness,
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
    package = EvidencePackage(
        package_code=code,
        package_version=f"{PACKAGE_VERSION}-{content_hash[:12]}",
        **values,
    )
    session.add(package)
    session.flush()
    previous = session.scalar(
        select(EvidencePackage)
        .where(EvidencePackage.package_code == code, EvidencePackage.id != package.id)
        .order_by(EvidencePackage.generated_at.desc(), EvidencePackage.id.desc())
    )
    if previous is not None and previous.superseded_by_id is None:
        previous.superseded_by_id = package.id
    return package, True


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
        hash_cache: HashCache = {}
        for index, comparison in enumerate(comparisons, start=1):
            source_value = comparison.source_value
            target_value = comparison.target_value
            if source_value is not None and not normalized_evidence_valid(
                session, source_value, hash_cache=hash_cache, now=now
            ):
                source_value = None
            if target_value is not None and not normalized_evidence_valid(
                session, target_value, hash_cache=hash_cache, now=now
            ):
                target_value = None
            source_ref = (
                ensure_reference(session, source_value.evidence_id, now)
                if source_value is not None
                else None
            )
            target_ref = (
                ensure_reference(session, target_value.evidence_id, now)
                if target_value is not None
                else None
            )
            _upsert_item(
                session=session,
                package=package,
                display_order=index,
                canonical_field_id=comparison.canonical_field_id,
                source_value_id=source_value.id if source_value is not None else None,
                target_value_id=target_value.id if target_value is not None else None,
                source_evidence_id=source_value.evidence_id if source_value is not None else None,
                target_evidence_id=target_value.evidence_id if target_value is not None else None,
                source_reference_code=source_ref.reference_code if source_ref is not None else None,
                target_reference_code=target_ref.reference_code if target_ref is not None else None,
                comparison_status=(
                    comparison.comparison_status
                    if source_value is not None and target_value is not None
                    else "insufficient_evidence"
                ),
                matched_status=comparison.semantic_status,
                scope_status=comparison.scope_status,
                qualifier_status=comparison.qualifier_status,
                freshness_status=FreshnessStatus.UNKNOWN.value,
                conflict_status="none",
                blocking_reason=(
                    "invalid_or_missing_current_normalized_evidence"
                    if source_value is None or target_value is None
                    else comparison.blocking_reason
                ),
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
    source_link = next(
        (
            link
            for link in links
            if link.evidence.source_document.provider_id == candidate.source_provider_id
        ),
        None,
    )
    target_link = next(
        (
            link
            for link in links
            if link.evidence.source_document.provider_id == candidate.target_provider_id
        ),
        None,
    )
    scoped_approval = mapping_approval(session, candidate)
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
        scope_status="match" if scoped_approval else "not_evaluated",
        qualifier_status="match" if scoped_approval else "not_evaluated",
        freshness_status=package.freshness_status,
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


def _normalized_dependency(
    session: Session,
    row: NormalizedSpecification | None,
    *,
    hash_cache: HashCache,
    now: datetime,
) -> dict[str, Any] | None:
    if row is None:
        return None
    valid = normalized_evidence_valid(session, row, hash_cache=hash_cache, now=now)
    spec = session.get(ProductSpecification, row.product_specification_id)
    evidence = session.get(Evidence, row.evidence_id)
    source = session.get(SourceDocument, evidence.source_document_id) if evidence else None
    snapshot = (
        session.get(SnapshotRecord, evidence.snapshot_record_id)
        if evidence and evidence.snapshot_record_id is not None
        else None
    )

    def time_key(value: datetime | None) -> str | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        ).isoformat()

    return {
        "current_valid": valid,
        "value": [
            row.id,
            row.product_id,
            row.sku_id,
            row.scope_type,
            row.scope_identity,
            row.source_value_hash,
            row.canonical_value,
            row.canonical_unit,
            row.value_qualifier,
        ],
        "spec": [
            spec.id,
            spec.evidence_id,
            spec.product_id,
            spec.sku_id,
            time_key(spec.valid_from),
            time_key(spec.valid_to),
        ]
        if spec
        else None,
        "evidence": [
            evidence.id,
            evidence.review_status,
            evidence.content_hash,
            evidence.source_document_id,
            evidence.snapshot_record_id,
        ]
        if evidence
        else None,
        "source": [
            source.id,
            source.is_current,
            source.content_hash,
            source.storage_path,
            source.provider_id,
            source.cloud_partition,
        ]
        if source
        else None,
        "snapshot": [
            snapshot.id,
            snapshot.source_document_id,
            snapshot.is_current,
            snapshot.content_hash,
            snapshot.storage_path,
            snapshot.content_length_bytes,
        ]
        if snapshot
        else None,
    }


def _content_hash(
    session: Session, candidate: MappingCandidate, *, now: datetime | None = None
) -> str:
    at = now or datetime.now(UTC)
    hash_cache: HashCache = {}
    comparisons = session.scalars(
        select(MappingFieldComparison)
        .where(MappingFieldComparison.mapping_candidate_id == candidate.id)
        .order_by(MappingFieldComparison.id)
    ).all()
    links = session.scalars(
        select(MappingCandidateEvidence)
        .where(MappingCandidateEvidence.mapping_candidate_id == candidate.id)
        .order_by(MappingCandidateEvidence.id)
    ).all()
    payload = {
        "generator_version": PACKAGE_VERSION,
        "candidate_id": candidate.id,
        "rule_set_version": candidate.rule_set.rule_set_version,
        "mapping_level": candidate.mapping_level,
        "source": [candidate.source_entity_type, candidate.source_entity_id],
        "target": [candidate.target_entity_type, candidate.target_entity_id],
        "relationship_type": candidate.relationship_type,
        "candidate_status": candidate.candidate_status,
        "review_status": candidate.review_status,
        "blocking_reasons": candidate.blocking_reasons,
        "conditions": candidate.conditions,
        "model_approval": mapping_approval(session, candidate),
        "freshness": _mapping_freshness(candidate, at),
        "links": [[link.evidence_id, link.evidence.source_document.content_hash] for link in links],
        "comparisons": [
            [
                row.id,
                row.source_value_id,
                row.target_value_id,
                row.source_value.review_status if row.source_value else None,
                row.target_value.review_status if row.target_value else None,
                row.source_value.evidence_id if row.source_value else None,
                row.target_value.evidence_id if row.target_value else None,
                _normalized_dependency(session, row.source_value, hash_cache=hash_cache, now=at),
                _normalized_dependency(session, row.target_value, hash_cache=hash_cache, now=at),
                row.comparison_status,
                row.evidence_status,
                row.semantic_status,
                row.unit_status,
                row.scope_status,
                row.qualifier_status,
                row.blocking_reason,
            ]
            for row in comparisons
        ],
    }
    # Actual digests, not only stored expected hashes; the cache is local to this candidate.
    payload["raw_digests"] = sorted(set(hash_cache.values()))
    digest = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    # Restoring a former state must create a successor, never resurrect a retired package.
    retired_hashes: dict[str, int] = dict(
        session.execute(
            select(EvidencePackage.content_hash, EvidencePackage.id).where(
                EvidencePackage.package_code == _package_code(candidate),
                EvidencePackage.superseded_by_id.is_not(None),
            )
        )
        .tuples()
        .all()
    )
    while digest in retired_hashes:
        digest = sha256(f"{digest}|superseded:{retired_hashes[digest]}".encode()).hexdigest()
    return digest


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
