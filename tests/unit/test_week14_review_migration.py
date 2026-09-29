from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun, ReviewItem
from cloud_expert.model_review.migration import migrate_precheck, review_queue_integrity


def test_migration_is_additive_and_idempotent(session: Session) -> None:
    item = ReviewItem(
        item_type="low_confidence_field",
        severity="high",
        status="open",
        reason="Synthetic source verification required",
    )
    session.add(item)
    session.flush()
    run = ModelReviewRun(
        run_code="synthetic_precheck_v1",
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
            subject_type="review_item",
            subject_id=item.id,
            verdict="requires_source_verification",
            reason_code="synthetic_review_needed",
            rationale="Synthetic test only",
            evidence_ids=[],
            input_hash="b" * 64,
        )
    )
    session.flush()

    preview = migrate_precheck(session, run.run_code)
    assert preview["would_create"] == 1
    assert preview["new_assignments"] == 0
    assert list(session.scalars(select(ModelReviewAssignment))) == []

    applied = migrate_precheck(session, run.run_code, apply=True)
    assert applied["new_assignments"] == 1
    assignment = session.scalar(select(ModelReviewAssignment))
    assert assignment is not None
    assert assignment.review_state == "pending_model_review"
    assert assignment.prior_review_status == "open"
    assert session.get(ReviewItem, item.id).status == "open"
    assert session.scalar(select(ModelReviewAuditEvent)) is not None

    again = migrate_precheck(session, run.run_code, apply=True)
    assert again["already_migrated"] == 1
    assert again["new_assignments"] == 0
    assert len(list(session.scalars(select(ModelReviewAssignment)))) == 1
    assert len(list(session.scalars(select(ModelReviewAuditEvent)))) == 1


def test_targeted_precheck_does_not_invalidate_full_queue(session: Session) -> None:
    for index, count in enumerate((3, 1)):
        run = ModelReviewRun(
            run_code=f"synthetic_batch_{index}",
            policy_version="test",
            reviewer_model="deterministic_evidence_precheck",
            input_fingerprint="a" * 64,
            reviewed_at=datetime.now(UTC),
            summary_json={},
        )
        session.add(run)
        session.flush()
        for _ in range(count):
            item = ReviewItem(
                item_type="low_confidence_field",
                severity="high",
                status="open",
                reason="Synthetic only",
            )
            session.add(item)
            session.flush()
            session.add(
                ModelReviewFinding(
                    run_id=run.id,
                    subject_type="review_item",
                    subject_id=item.id,
                    verdict="requires_source_verification",
                    reason_code="synthetic",
                    rationale="Synthetic only",
                    evidence_ids=[],
                    input_hash="b" * 64,
                )
            )
        session.flush()
        migrate_precheck(session, run.run_code, apply=True)
    integrity = review_queue_integrity(session)
    assert integrity == {
        "tracked_precheck_runs": 2,
        "tracked_findings": 4,
        "assignments": 4,
        "missing_assignments": 0,
        "invalid_assignments": 0,
    }
    assignment = session.scalar(select(ModelReviewAssignment))
    assignment.input_hash = "c" * 64
    session.flush()
    assert review_queue_integrity(session)["invalid_assignments"] == 1


def test_latest_unmigrated_precheck_is_detected(session: Session) -> None:
    run = ModelReviewRun(
        run_code="synthetic_unmigrated",
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
            subject_type="review_item",
            subject_id=1,
            verdict="requires_source_verification",
            reason_code="synthetic",
            rationale="Synthetic only",
            evidence_ids=[],
            input_hash="b" * 64,
        )
    )
    session.flush()
    assert review_queue_integrity(session)["missing_assignments"] == 1
