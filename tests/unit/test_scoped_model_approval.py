import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.evidence_packages.references import freshness_for
from cloud_expert.mapping.pipeline import _ensure_rule_sets, _upsert_candidate
from cloud_expert.model_review import approvals, workflow
from cloud_expert.model_review.approvals import mapping_approval
from tests.fixtures.synthetic_data import load_synthetic_fixture
from tests.unit.test_week14_pilot_writeback import _mock_verified_synthetic_runtime, _report


@pytest.fixture
def scoped_review(session: Session, tmp_path: Path, monkeypatch):
    _mock_verified_synthetic_runtime(monkeypatch)
    monkeypatch.setattr(approvals, "mapping_evidence_valid", lambda *_: True)
    fixture = load_synthetic_fixture(session)
    source, target = fixture["product"], fixture["competitor_product"]
    target.market_mode = "domestic"
    now = datetime.now(UTC)
    rule = _ensure_rule_sets(session, now)["week07_product"]
    candidate = _upsert_candidate(
        session=session,
        rule_set=rule,
        mapping_level="product",
        source_provider_id=source.provider_id,
        source_entity_type="product",
        source_entity_id=source.id,
        target_provider_id=target.provider_id,
        target_entity_type="product",
        target_entity_id=target.id,
        relationship_type="same_service_class",
        candidate_status="candidate",
        raw_score=None,
        normalized_score=None,
        confidence=None,
        blocking_reasons=[],
        conditions=[
            "product-level service category only; no SKU, price, SLA or performance equivalence"
        ],
        explanation="Synthetic category-only mapping",
        now=now,
    )
    run = ModelReviewRun(
        run_code="synthetic_scoped",
        policy_version="test",
        reviewer_model="deterministic_evidence_precheck",
        input_fingerprint="a" * 64,
        reviewed_at=now,
        summary_json={},
    )
    session.add(run)
    session.flush()
    finding = ModelReviewFinding(
        run_id=run.id,
        subject_type="mapping_candidate",
        subject_id=candidate.id,
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
        target_id=candidate.id,
        input_hash=finding.input_hash,
        prior_review_status="pending_review",
        review_state="pending_model_review",
        evidence_ids=[10],
    )
    session.add(assignment)
    session.flush()
    payload = {
        "target_type": "mapping_candidate",
        "target_id": candidate.id,
        "precheck_run_code": run.run_code,
        "precheck_verdict": "requires_dual_model_review",
        "evidence": [{"evidence_id": 10}],
    }
    monkeypatch.setattr(workflow, "mapping_review_input", lambda *_: payload)
    report = _report(tmp_path, payload, final="model_approved_with_conditions")
    summary = json.loads((report / "summary.json").read_text())
    summary["target_id"] = candidate.id
    (report / "summary.json").write_text(json.dumps(summary))
    primary_path = report / "primary/response.json"
    primary = json.loads(primary_path.read_text())
    primary.update(
        decision="model_approved_with_conditions",
        supported_by_evidence=True,
        field_semantics_correct=True,
        scope_correct=True,
        market_scope_correct=True,
        conditions=[
            "Product-level service category only; no SKU, price, SLA, or performance equivalence."
        ],
        blocking_reasons=[],
    )
    primary_path.write_text(json.dumps(primary))
    adversarial_path = report / "adversarial/response.json"
    adversarial = json.loads(adversarial_path.read_text())
    adversarial["recommended_decision"] = "model_approved_with_conditions"
    adversarial_path.write_text(json.dumps(adversarial))
    return candidate, assignment, report


def test_scoped_approval_idempotent_preserves_legacy_status(session: Session, scoped_review):
    candidate, assignment, report = scoped_review
    result = workflow.apply_mapping_pilot_result(session, report, approved_model="gpt-6-astra")
    assert result["status"] == "applied_scoped_approval"
    assert candidate.candidate_status == "approved"
    assert candidate.review_status == "pending_review"
    assert assignment.review_state == "model_approved_with_conditions"
    assert mapping_approval(session, candidate) is not None
    assert mapping_approval(session, candidate, scope="sku_equivalence") is None
    assert mapping_approval(session, candidate, scope="price_equivalence") is None
    again = workflow.apply_mapping_pilot_result(session, report, approved_model="gpt-6-astra")
    assert again["status"] == "already_applied"
    assert len(list(session.scalars(select(ModelReviewAuditEvent)))) == 1
    candidate.conditions = []
    assert mapping_approval(session, candidate) is None
    with pytest.raises(ValueError):
        workflow.apply_mapping_pilot_result(session, report, approved_model="gpt-6-astra")


@pytest.mark.parametrize(
    "field,value",
    [
        ("conditions", ["Prices must be checked manually later"]),
        ("blocking_reasons", ["Missing source"]),
        ("required_repairs", ["Reparse source"]),
        ("evidence_references", []),
        ("scope_correct", False),
    ],
)
def test_unresolved_review_cannot_approve(session: Session, scoped_review, field, value):
    candidate, assignment, report = scoped_review
    path = report / "primary/response.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        workflow.apply_mapping_pilot_result(session, report, approved_model="gpt-6-astra")
    assert assignment.review_state == "pending_model_review"
    assert candidate.candidate_status == "candidate"
    assert session.scalar(select(ModelReviewAuditEvent)) is None


@pytest.mark.parametrize(
    "days,current,expected",
    [
        (0, True, "fresh"),
        (74, True, "due_soon"),
        (91, True, "stale"),
        (-1, True, "unknown"),
        (1, False, "unknown"),
    ],
)
def test_freshness_checks_current_and_future_dates(days, current, expected):
    now = datetime.now(UTC)
    source = SourceDocument(
        source_type="documentation", captured_at=now - timedelta(days=days), is_current=current
    )
    assert freshness_for(source, now) == expected


def test_approval_cannot_survive_scope_or_candidate_change(session: Session, scoped_review):
    candidate, _, report = scoped_review
    workflow.apply_mapping_pilot_result(session, report, approved_model="gpt-6-astra")
    candidate.explanation = "Synthetic unsupported superiority claim"
    assert mapping_approval(session, candidate) is None
    assert session.get(MappingCandidate, candidate.id).review_status != "human_reviewed"
