from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.review import ModelReviewRun
from cloud_expert.model_review.approvals import (
    PRODUCT_CATEGORY_CONDITIONS,
    PRODUCT_CATEGORY_SCOPE,
    mapping_subject_hash,
)
from cloud_expert.model_review.pilot import _fingerprint, mapping_review_input
from cloud_expert.model_review.schemas import (
    AdversarialReview,
    Decision,
    PrimaryReview,
    conservative_resolution,
    validate_review_evidence,
)

UNRESOLVED_REVIEW_STATES = frozenset(
    {
        "pending_model_review",
        "blocked_by_deterministic_check",
        "model_review_in_progress",
        "model_approved_with_conditions",
        "model_rejected_reparse",
        "model_inconclusive",
        "model_blocked",
        "expired",
    }
)
NON_APPROVAL_DECISIONS = frozenset({Decision.REPARSE, Decision.INCONCLUSIVE, Decision.BLOCKED})


def unresolved_review_count(states: Counter[str] | dict[str, int]) -> int:
    return sum(states.get(state, 0) for state in UNRESOLVED_REVIEW_STATES)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path.name}")
    return value


def apply_nonapproval_pilot_result(
    session: Session, report_dir: Path, *, approved_model: str
) -> dict[str, Any]:
    return apply_mapping_pilot_result(
        session, report_dir, approved_model=approved_model, allow_approval=False
    )


def apply_mapping_pilot_result(
    session: Session, report_dir: Path, *, approved_model: str, allow_approval: bool = True
) -> dict[str, Any]:
    summary = _read_json(report_dir / "summary.json")
    payload = _read_json(report_dir / "input.json")
    if (
        summary.get("status") != "completed"
        or summary.get("model_id") != approved_model
        or summary.get("customer_eligible") is not False
        or summary.get("database_writeback") is not False
        or payload.get("target_type") != "mapping_candidate"
        or summary.get("target_id") != payload.get("target_id")
    ):
        raise ValueError("pilot report is not a completed, internal-only mapping review")
    if summary.get("input_hash") != _fingerprint({"payload": payload, "model_id": approved_model}):
        raise ValueError("pilot input differs from current evidence-backed candidate")
    evidence_ids = {row["evidence_id"] for row in payload["evidence"]}
    primary = PrimaryReview.model_validate_json(
        (report_dir / "primary/response.json").read_text(encoding="utf-8")
    )
    adversarial = AdversarialReview.model_validate_json(
        (report_dir / "adversarial/response.json").read_text(encoding="utf-8")
    )
    validate_review_evidence(primary, evidence_ids)
    validate_review_evidence(adversarial, evidence_ids)
    needs_adjudication = (
        adversarial.verdict != "agree" or primary.decision != adversarial.recommended_decision
    )
    adjudication: PrimaryReview | None = None
    stages = ["primary", "adversarial"]
    if needs_adjudication:
        adjudication = PrimaryReview.model_validate_json(
            (report_dir / "adjudication/response.json").read_text(encoding="utf-8")
        )
        validate_review_evidence(adjudication, evidence_ids)
        stages.append("adjudication")
    sessions = [summary.get(f"{stage}_session_id") for stage in stages]
    if any(not session_id for session_id in sessions) or len(set(sessions)) != len(sessions):
        raise ValueError("review stage sessions are missing or not independent")
    for stage in stages:
        execution = _read_json(report_dir / stage / "execution.json")
        if execution.get("stage") != stage or execution.get("exit_code") != 0:
            raise ValueError(f"{stage} did not complete successfully")
    final = conservative_resolution(payload["precheck_verdict"], primary, adversarial, adjudication)
    if (not allow_approval and final not in NON_APPROVAL_DECISIONS) or summary.get(
        "final_decision"
    ) != final.value:
        raise ValueError("result is either approvable or inconsistent with conservative consensus")
    approving = final in {Decision.APPROVED, Decision.CONDITIONAL}
    candidate = session.get(MappingCandidate, payload["target_id"]) if approving else None
    decision_review = adjudication or primary
    if approving and (
        candidate is None
        or candidate.mapping_level != "product"
        or candidate.relationship_type != "same_service_class"
        or not candidate.conditions
        or not set(candidate.conditions).issubset(PRODUCT_CATEGORY_CONDITIONS)
        or not set(decision_review.conditions).issubset(PRODUCT_CATEGORY_CONDITIONS)
        or primary.blocking_reasons
        or primary.required_repairs
        or decision_review.blocking_reasons
        or decision_review.required_repairs
        or adversarial.identified_errors
        or adversarial.missing_conditions
        or set(primary.evidence_references) != evidence_ids
        or set(adversarial.evidence_references) != evidence_ids
    ):
        raise ValueError(
            "approval has unenforced conditions, incomplete citations or unresolved errors"
        )
    run = session.scalar(
        select(ModelReviewRun).where(ModelReviewRun.run_code == payload["precheck_run_code"])
    )
    if run is None:
        raise ValueError("precheck run no longer exists")
    assignment = session.scalar(
        select(ModelReviewAssignment).where(
            ModelReviewAssignment.precheck_run_id == run.id,
            ModelReviewAssignment.target_type == "mapping_candidate",
            ModelReviewAssignment.target_id == payload["target_id"],
        )
    )
    if assignment is None or set(assignment.evidence_ids) != evidence_ids:
        raise ValueError("assignment is missing or evidence identities differ")
    event_code = "pilot_" + sha256(str(report_dir.resolve()).encode("utf-8")).hexdigest()[:24]
    existing = session.scalar(
        select(ModelReviewAuditEvent).where(
            ModelReviewAuditEvent.assignment_id == assignment.id,
            ModelReviewAuditEvent.event_code == event_code,
        )
    )
    if existing is not None:
        if (
            approving
            and candidate is not None
            and not any(
                record.get("subject_hash") == mapping_subject_hash(candidate)
                for record in existing.affected_records
            )
        ):
            raise ValueError("approved candidate changed after writeback")
        return {
            "status": "already_applied",
            "assignment_id": assignment.id,
            "event_id": existing.id,
        }
    if assignment.review_state != "pending_model_review":
        raise ValueError("assignment state changed since pilot input was prepared")
    current = mapping_review_input(session, payload["precheck_run_code"], payload["target_id"])
    if current != payload:
        raise ValueError("pilot input differs from current evidence-backed candidate")
    now = datetime.now(UTC)
    prior = assignment.review_state
    assignment.review_state = final.value
    assignment.updated_at = now
    approval_metadata: dict[str, Any] = {}
    if approving and candidate is not None:
        approval_metadata = {
            "subject_hash": mapping_subject_hash(candidate),
            "approved_scope": PRODUCT_CATEGORY_SCOPE,
            "conditions_enforced": True,
            "review_conditions": decision_review.conditions,
        }
        candidate.candidate_status = "approved"
    event = ModelReviewAuditEvent(
        assignment_id=assignment.id,
        event_code=event_code,
        previous_status=prior,
        new_status=final.value,
        source="independent_model_review",
        model_id=approved_model,
        reason="scoped_mapping_approval" if approving else "source_evidence_insufficient",
        affected_records=[
            {
                "target_type": "mapping_candidate",
                "target_id": payload["target_id"],
                "evidence_ids": sorted(evidence_ids),
                "input_hash": summary["input_hash"],
                "report_dir": str(report_dir.resolve()),
                "stage_session_ids": sessions,
                **approval_metadata,
            }
        ],
        downstream_rebuild_required=approving or final == Decision.REPARSE,
        timestamp=now,
    )
    session.add(event)
    session.commit()
    return {
        "status": "applied_scoped_approval" if approving else "applied_nonapproval",
        "assignment_id": assignment.id,
        "event_id": event.id,
        "prior_state": prior,
        "new_state": final.value,
        "business_mapping_modified": approving,
        "customer_eligible": False,
    }
