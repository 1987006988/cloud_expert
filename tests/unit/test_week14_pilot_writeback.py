import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.model_review import workflow
from cloud_expert.model_review.schemas import AdversarialReview, Decision, PrimaryReview


def _report(tmp_path: Path, payload: dict, *, final: str = "model_inconclusive") -> Path:
    report_dir = tmp_path / "mapping_42_synthetic"
    report_dir.mkdir()
    (report_dir / "input.json").write_text(json.dumps(payload), encoding="utf-8")
    summary = {
        "status": "completed",
        "model_id": "gpt-6-astra",
        "target_id": 42,
        "input_hash": workflow._fingerprint({"payload": payload, "model_id": "gpt-6-astra"}),
        "customer_eligible": False,
        "database_writeback": False,
        "primary_session_id": "primary-session",
        "adversarial_session_id": "adversarial-session",
        "final_decision": final,
    }
    (report_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    primary = PrimaryReview(
        decision=Decision.INCONCLUSIVE,
        confidence=0.9,
        supported_by_evidence=False,
        field_semantics_correct=False,
        scope_correct=False,
        market_scope_correct=False,
        conditions=[],
        blocking_reasons=["Synthetic evidence gap"],
        required_repairs=[],
        evidence_references=[10],
        reasoning_summary="Synthetic only.",
    )
    adversarial = AdversarialReview(
        verdict="agree",
        identified_errors=[],
        missing_conditions=[],
        recommended_decision=Decision.INCONCLUSIVE,
        confidence=0.9,
        evidence_references=[10],
        reasoning_summary="Synthetic only.",
    )
    for stage, review in (("primary", primary), ("adversarial", adversarial)):
        stage_dir = report_dir / stage
        stage_dir.mkdir()
        (stage_dir / "response.json").write_text(review.model_dump_json(), encoding="utf-8")
        (stage_dir / "execution.json").write_text(
            json.dumps({"stage": stage, "exit_code": 0}), encoding="utf-8"
        )
    return report_dir


def test_nonapproval_writeback_is_audited_idempotent_and_still_blocks_gate(
    session: Session, tmp_path: Path, monkeypatch
) -> None:
    run = ModelReviewRun(
        run_code="synthetic_mapping_precheck",
        policy_version="test",
        reviewer_model="deterministic_evidence_precheck",
        input_fingerprint="a" * 64,
        reviewed_at=datetime.now(UTC),
        summary_json={},
    )
    session.add(run)
    session.flush()
    finding = ModelReviewFinding(
        run_id=run.id,
        subject_type="mapping_candidate",
        subject_id=42,
        verdict="requires_dual_model_review",
        reason_code="synthetic",
        rationale="Synthetic only",
        evidence_ids=[10],
        input_hash="b" * 64,
    )
    session.add(finding)
    session.flush()
    assignment = ModelReviewAssignment(
        precheck_run_id=run.id,
        precheck_finding_id=finding.id,
        target_type="mapping_candidate",
        target_id=42,
        input_hash=finding.input_hash,
        prior_review_status="pending_review",
        review_state="pending_model_review",
        evidence_ids=[10],
    )
    session.add(assignment)
    session.flush()
    payload = {
        "target_type": "mapping_candidate",
        "target_id": 42,
        "precheck_run_code": run.run_code,
        "precheck_verdict": "requires_dual_model_review",
        "evidence": [{"evidence_id": 10}],
    }
    monkeypatch.setattr(workflow, "mapping_review_input", lambda *_: payload)
    report_dir = _report(tmp_path, payload)

    result = workflow.apply_nonapproval_pilot_result(
        session, report_dir, approved_model="gpt-6-astra"
    )
    assert result["status"] == "applied_nonapproval"
    assert assignment.review_state == "model_inconclusive"
    assert workflow.unresolved_review_count({assignment.review_state: 1}) == 1
    event = session.scalar(select(ModelReviewAuditEvent))
    assert event is not None
    assert event.previous_status == "pending_model_review"
    assert event.new_status == "model_inconclusive"
    assert event.model_id == "gpt-6-astra"
    assert event.downstream_rebuild_required is False

    again = workflow.apply_nonapproval_pilot_result(
        session, report_dir, approved_model="gpt-6-astra"
    )
    assert again["status"] == "already_applied"
    assert len(list(session.scalars(select(ModelReviewAuditEvent)))) == 1


def test_inconsistent_summary_cannot_be_written(
    session: Session, tmp_path: Path, monkeypatch
) -> None:
    payload = {
        "target_type": "mapping_candidate",
        "target_id": 42,
        "precheck_run_code": "synthetic",
        "precheck_verdict": "requires_dual_model_review",
        "evidence": [{"evidence_id": 10}],
    }
    monkeypatch.setattr(workflow, "mapping_review_input", lambda *_: payload)
    report_dir = _report(tmp_path, payload, final="model_approved")
    with pytest.raises(ValueError, match="approvable or inconsistent"):
        workflow.apply_nonapproval_pilot_result(session, report_dir, approved_model="gpt-6-astra")
