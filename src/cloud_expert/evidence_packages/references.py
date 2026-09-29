from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    AuthorityLevel,
    EvidenceReliabilityLevel,
    EvidenceStatus,
    FreshnessStatus,
    SourceType,
)
from cloud_expert.database.models.evidence_package import EvidenceReference
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.source import Evidence, SourceDocument


def reference_code_for(evidence: Evidence, provider_code: str) -> str:
    source = evidence.source_document
    basis = (
        f"{provider_code}|{source.url}|{source.content_hash}|{evidence.locator}|{evidence.excerpt}"
    )
    digest = sha256(basis.encode("utf-8")).hexdigest()[:8].upper()
    return f"EV-{provider_code.upper()}-{source.source_type[:3].upper()}-{evidence.id}-{digest}"


def reliability_for(source_document: SourceDocument) -> str:
    if source_document.authority_level not in {
        AuthorityLevel.OFFICIAL_PRIMARY.value,
        AuthorityLevel.OFFICIAL_SECONDARY.value,
    }:
        return EvidenceReliabilityLevel.UNKNOWN.value
    source_type = source_document.source_type
    if source_type == SourceType.SPECIFICATION.value:
        return EvidenceReliabilityLevel.OFFICIAL_SPECIFICATION.value
    if source_type == SourceType.SLA.value:
        return EvidenceReliabilityLevel.OFFICIAL_SLA.value
    if source_type == SourceType.PRODUCT_PAGE.value:
        return EvidenceReliabilityLevel.OFFICIAL_PRODUCT_PAGE.value
    if source_type == SourceType.RELEASE_NOTE.value:
        return EvidenceReliabilityLevel.OFFICIAL_RELEASE_NOTE.value
    if source_type == SourceType.API_RESPONSE.value:
        return EvidenceReliabilityLevel.OFFICIAL_STRUCTURED.value
    if source_type in {SourceType.DOCUMENTATION.value, SourceType.REGION_AVAILABILITY.value}:
        return EvidenceReliabilityLevel.OFFICIAL_DOCUMENTATION.value
    return EvidenceReliabilityLevel.UNKNOWN.value


def freshness_for(source_document: SourceDocument, now: datetime) -> str:
    if source_document.source_type == SourceType.RELEASE_NOTE.value:
        return FreshnessStatus.HISTORICAL.value
    captured = source_document.captured_at
    if captured is None:
        return FreshnessStatus.UNKNOWN.value
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    if not source_document.is_current or captured > now:
        return FreshnessStatus.UNKNOWN.value
    age_days = (now - captured).days
    cycle_days = {
        SourceType.SPECIFICATION.value: 30,
        SourceType.REGION_AVAILABILITY.value: 14,
        SourceType.DOCUMENTATION.value: 90,
        SourceType.SLA.value: 30,
        SourceType.PRODUCT_PAGE.value: 180,
    }.get(source_document.source_type, 90)
    if age_days > cycle_days:
        return FreshnessStatus.STALE.value
    if age_days > int(cycle_days * 0.8):
        return FreshnessStatus.DUE_SOON.value
    return FreshnessStatus.FRESH.value


def status_for(evidence: Evidence) -> str:
    if evidence.review_status == "rejected":
        return EvidenceStatus.REJECTED.value
    if evidence.snapshot_record_id is None:
        return EvidenceStatus.UNVERIFIABLE.value
    if evidence.content_hash and evidence.source_document.content_hash != evidence.content_hash:
        return EvidenceStatus.CONFLICTING.value
    if evidence.review_status == "pending_review":
        return EvidenceStatus.PENDING_REVIEW.value
    return EvidenceStatus.ACTIVE.value


def ensure_reference(session: Session, evidence_id: int, now: datetime) -> EvidenceReference:
    existing = session.scalar(
        select(EvidenceReference).where(EvidenceReference.evidence_id == evidence_id)
    )
    if existing is not None:
        return existing
    evidence = session.get(Evidence, evidence_id)
    if evidence is None:
        raise ValueError(f"evidence_id={evidence_id} not found")
    provider = session.get(Provider, evidence.source_document.provider_id)
    provider_code = provider.code if provider is not None else "unknown"
    source = evidence.source_document
    reference = EvidenceReference(
        reference_code=reference_code_for(evidence, provider_code),
        evidence_id=evidence.id,
        snapshot_id=evidence.snapshot_record_id,
        content_hash=evidence.content_hash or source.content_hash,
        locator=evidence.locator,
        excerpt=evidence.excerpt,
        source_title=source.title,
        source_url=source.url,
        captured_at=source.captured_at,
        published_at=source.published_at,
        reliability_level=reliability_for(source),
        evidence_status=status_for(evidence),
        freshness_status=freshness_for(source, now),
        created_at=now,
    )
    session.add(reference)
    session.flush()
    return reference
