"""Narrow internal cost-use readiness, never a customer or whole-week approval."""

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cloud_expert.model_review.decision_panel import SCOPED_REVIEW, build_decision_packet
from cloud_expert.model_review.decision_writeback import current_internal_decision_approval


def internal_cost_readiness(
    session: Session,
    candidate_id: int,
    *,
    raw_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Require live joined inputs and a separately executed, current model panel."""
    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "scope": SCOPED_REVIEW,
        "valid": False,
        "blocking_items": [],
        "customer_output_allowed": False,
        "rank_authorized": False,
        "production_authorized": False,
        "week11_complete": False,
        "allowed_operations": [],
    }
    if candidate_id <= 0:
        result["blocking_items"] = ["invalid_candidate_id"]
        return result
    try:
        packet = build_decision_packet(session, candidate_id, raw_root=raw_root, now=now)
        payload = packet.payload
        if payload["data_classification"] != "official_public":
            result["blocking_items"] = ["real_official_evidence_required"]
            return result
        if payload["review_scope"] != SCOPED_REVIEW:
            result["blocking_items"] = ["unsupported_internal_scope"]
            return result
        approval = current_internal_decision_approval(
            session, candidate_id, scope=SCOPED_REVIEW, raw_root=raw_root, now=now
        )
        if approval is None:
            result["blocking_items"] = ["current_independent_model_approval_required"]
            return result
        if (
            approval.get("input_fingerprint") != packet.fingerprint
            or payload["subject"]["id"] != candidate_id
            or approval.get("review_scope") != SCOPED_REVIEW
            or approval.get("customer_eligible") is not False
            or approval.get("rank_authorized") is not False
        ):
            result["blocking_items"] = ["approval_binding_or_scope_mismatch"]
            return result
        result.update(
            valid=True,
            input_fingerprint=packet.fingerprint,
            decision_review_id=approval["decision_review_id"],
            approval_expires_at=approval["expires_at"],
            mapping_candidate_id=payload["subject"]["mapping_candidate_id"],
            tco_result_id=payload["subject"]["tco_result_id"],
            scenario=payload["scenario"],
            evidence_package_ids=payload["evidence_package_ids"],
            evidence_ids=approval["evidence_ids"],
            review_conditions=approval.get("conditions", []),
            limitations=payload["limitations"],
            allowed_operations=["view_reviewed_bounded_cost", "develop_internal_cost_brief"],
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result["blocking_items"] = ["live_dependency_validation_failed"]
        # Keep diagnostics local; this report is never a customer export.
        result["diagnostic"] = str(exc)
    return result
