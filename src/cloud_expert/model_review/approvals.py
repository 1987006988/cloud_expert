from __future__ import annotations

from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.model_review.pilot import OFFICIAL_HOSTS, RAW_ROOT, _fingerprint

PRODUCT_CATEGORY_SCOPE = "product_category_only"
PRODUCT_CATEGORY_CONDITIONS = frozenset(
    {
        "product-level service category only; no SKU, price, SLA or performance equivalence",
        "Product-level service category only; no SKU, price, SLA, or performance equivalence.",
    }
)


def mapping_evidence_valid(session: Session, candidate: MappingCandidate) -> bool:
    if not candidate.evidence_links:
        return False
    for link in candidate.evidence_links:
        evidence = link.evidence
        document = evidence.source_document
        snapshot = (
            session.get(SnapshotRecord, evidence.snapshot_record_id)
            if evidence.snapshot_record_id
            else None
        )
        url = urlsplit(document.url)
        host = (url.hostname or "").lower()
        if (
            snapshot is None
            or not snapshot.is_current
            or not document.is_current
            or evidence.review_status == "rejected"
            or document.authority_level not in {"official_primary", "official_secondary"}
            or url.scheme != "https"
            or not any(host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_HOSTS)
            or snapshot.source_document_id != document.id
            or snapshot.content_hash != document.content_hash
            or evidence.content_hash not in {None, snapshot.content_hash}
        ):
            return False
        path = (RAW_ROOT / snapshot.storage_path).resolve()
        try:
            if (
                not path.is_relative_to(RAW_ROOT)
                or sha256(path.read_bytes()).hexdigest() != snapshot.content_hash
            ):
                return False
        except OSError:
            return False
    return True


def mapping_subject_hash(candidate: MappingCandidate) -> str:
    """Bind approval to facts and scope, independently of derived package/status changes."""
    return _fingerprint(
        {
            "id": candidate.id,
            "rule": [candidate.rule_set_id, candidate.rule_set.rule_set_version],
            "market": candidate.rule_set.market_mode,
            "source": [
                candidate.source_provider_id,
                candidate.source_entity_type,
                candidate.source_entity_id,
            ],
            "target": [
                candidate.target_provider_id,
                candidate.target_entity_type,
                candidate.target_entity_id,
            ],
            "level": candidate.mapping_level,
            "relationship": candidate.relationship_type,
            "explanation": candidate.explanation,
            "conditions": candidate.conditions,
            "blockers": candidate.blocking_reasons,
            "evidence": [
                [
                    link.evidence_id,
                    link.evidence_role,
                    link.evidence.locator,
                    link.evidence.excerpt,
                    link.evidence.content_hash,
                    link.evidence.source_document.content_hash,
                    link.evidence.source_document.url,
                    link.evidence.source_document.cloud_partition,
                ]
                for link in sorted(candidate.evidence_links, key=lambda item: item.evidence_id)
            ],
        }
    )


def mapping_approval(
    session: Session, candidate: MappingCandidate, *, scope: str = PRODUCT_CATEGORY_SCOPE
) -> dict[str, Any] | None:
    if candidate.candidate_status != "approved" or candidate.blocking_reasons:
        return None
    if scope != PRODUCT_CATEGORY_SCOPE or candidate.mapping_level != "product":
        return None
    if not mapping_evidence_valid(session, candidate):
        return None
    assignment = session.scalar(
        select(ModelReviewAssignment)
        .where(
            ModelReviewAssignment.target_type == "mapping_candidate",
            ModelReviewAssignment.target_id == candidate.id,
        )
        .order_by(ModelReviewAssignment.id.desc())
    )
    if assignment is None or assignment.review_state not in {
        "model_approved",
        "model_approved_with_conditions",
    }:
        return None
    event = session.scalar(
        select(ModelReviewAuditEvent)
        .where(ModelReviewAuditEvent.assignment_id == assignment.id)
        .order_by(ModelReviewAuditEvent.id.desc())
    )
    if (
        event is None
        or event.source != "independent_model_review"
        or event.new_status != assignment.review_state
    ):
        return None
    subject_hash = mapping_subject_hash(candidate)
    for record in event.affected_records:
        if (
            record.get("target_id") == candidate.id
            and record.get("subject_hash") == subject_hash
            and record.get("approved_scope") == scope
            and record.get("conditions_enforced") is True
        ):
            return {
                **record,
                "event_id": event.id,
                "model_id": event.model_id,
                "review_state": assignment.review_state,
            }
    return None
