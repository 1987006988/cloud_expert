from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import ComparabilityAssessment
from cloud_expert.database.models.decision import CandidateDecisionResult
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun, ReviewItem

MODEL_ELIGIBLE_PRECHECK = {"requires_dual_model_review", "requires_source_verification"}


def review_queue_integrity(session: Session) -> dict[str, int]:
    assignments = list(session.scalars(select(ModelReviewAssignment)))
    latest = session.scalar(
        select(ModelReviewRun)
        .where(ModelReviewRun.reviewer_model == "deterministic_evidence_precheck")
        .order_by(ModelReviewRun.id.desc())
    )
    run_ids = {row.precheck_run_id for row in assignments}
    if latest is not None:
        run_ids.add(latest.id)
    findings = {
        row.id: row
        for row in session.scalars(
            select(ModelReviewFinding).where(ModelReviewFinding.run_id.in_(run_ids))
        )
    }
    assigned_ids = {row.precheck_finding_id for row in assignments}
    invalid = 0
    for row in assignments:
        finding = findings.get(row.precheck_finding_id)
        if (
            finding is None
            or finding.run_id != row.precheck_run_id
            or finding.subject_type != row.target_type
            or finding.subject_id != row.target_id
            or finding.input_hash != row.input_hash
            or set(finding.evidence_ids) != set(row.evidence_ids)
        ):
            invalid += 1
    return {
        "tracked_precheck_runs": len(run_ids),
        "tracked_findings": len(findings),
        "assignments": len(assignments),
        "missing_assignments": len(set(findings) - assigned_ids),
        "invalid_assignments": invalid,
    }


def _legacy_statuses(session: Session) -> dict[str, dict[int, str]]:
    return {
        "review_item": {
            row[0]: row[1] for row in session.execute(select(ReviewItem.id, ReviewItem.status))
        },
        "mapping_candidate": {
            row[0]: row[1]
            for row in session.execute(
                select(MappingCandidate.id, MappingCandidate.candidate_status)
            )
        },
        "comparability_assessment": {
            row[0]: row[1]
            for row in session.execute(
                select(ComparabilityAssessment.id, ComparabilityAssessment.review_status)
            )
        },
        "candidate_decision_result": {
            row[0]: row[1]
            for row in session.execute(
                select(CandidateDecisionResult.id, CandidateDecisionResult.review_status)
            )
        },
    }


def _assignment_state(finding: ModelReviewFinding, prior_status: str | None) -> str:
    if finding.subject_type == "mapping_candidate" and prior_status in {"rejected", "superseded"}:
        return "blocked_by_deterministic_check"
    if finding.verdict in MODEL_ELIGIBLE_PRECHECK:
        return "pending_model_review"
    return "blocked_by_deterministic_check"


def migrate_precheck(
    session: Session, precheck_run_code: str, *, apply: bool = False
) -> dict[str, Any]:
    run = session.scalar(select(ModelReviewRun).where(ModelReviewRun.run_code == precheck_run_code))
    if run is None or run.reviewer_model != "deterministic_evidence_precheck":
        raise ValueError("selected run is not a deterministic precheck")
    findings = list(
        session.scalars(
            select(ModelReviewFinding)
            .where(ModelReviewFinding.run_id == run.id)
            .order_by(ModelReviewFinding.id)
        )
    )
    statuses = _legacy_statuses(session)
    existing_ids = set(
        session.scalars(
            select(ModelReviewAssignment.precheck_finding_id).where(
                ModelReviewAssignment.precheck_run_id == run.id
            )
        )
    )
    states: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    missing_target = 0
    pending: list[tuple[ModelReviewFinding, str | None, str]] = []
    for finding in findings:
        prior = statuses.get(finding.subject_type, {}).get(finding.subject_id)
        if prior is None:
            missing_target += 1
            continue
        state = _assignment_state(finding, prior)
        states[state] += 1
        by_type[finding.subject_type] += 1
        if finding.id not in existing_ids:
            pending.append((finding, prior, state))
    if apply and missing_target:
        raise ValueError(f"{missing_target} precheck targets no longer exist")
    if apply:
        now = datetime.now(UTC)
        for finding, prior, state in pending:
            assignment = ModelReviewAssignment(
                precheck_run_id=run.id,
                precheck_finding_id=finding.id,
                target_type=finding.subject_type,
                target_id=finding.subject_id,
                input_hash=finding.input_hash,
                prior_review_status=prior,
                review_state=state,
                evidence_ids=finding.evidence_ids,
                updated_at=now,
            )
            session.add(assignment)
            session.flush()
            session.add(
                ModelReviewAuditEvent(
                    assignment_id=assignment.id,
                    event_code=f"precheck_migration_{finding.id}",
                    previous_status=None,
                    new_status=state,
                    source="deterministic_precheck_migration",
                    model_id=None,
                    reason=finding.reason_code,
                    affected_records=[
                        {"target_type": finding.subject_type, "target_id": finding.subject_id}
                    ],
                    downstream_rebuild_required=False,
                    timestamp=now,
                )
            )
        session.commit()
    return {
        "precheck_run_code": precheck_run_code,
        "finding_count": len(findings),
        "by_target_type": dict(by_type),
        "review_states": dict(states),
        "already_migrated": len(existing_ids),
        "new_assignments": len(pending) if apply else 0,
        "would_create": len(pending),
        "missing_targets": missing_target,
        "legacy_review_rows_modified": 0,
        "applied": apply,
    }
