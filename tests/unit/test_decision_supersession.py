"""Synthetic-only Decision history tests. No models, sources or business DBs."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models.decision import (
    CandidateDecisionResult,
    DecisionRun,
    DecisionScenario,
    ScoringPolicy,
)
from cloud_expert.database.models.mapping import MappingCandidate, MappingRuleSet
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.decision import pipeline
from cloud_expert.model_review import decision_supersession as supersession
from cloud_expert.model_review.decision_supersession import (
    DecisionSupersessionPlan,
    SupersessionConflict,
    apply_decision_supersession,
    plan_decision_supersession,
)
from tests.fixtures.synthetic_data import load_synthetic_fixture


def add_run(
    session,
    scenario,
    mapping,
    number,
    *,
    decision_status="blocked",
    run_status="succeeded",
    with_result=True,
):
    at = datetime.now(UTC) - timedelta(minutes=20 - number)
    policy = scenario.scoring_policy
    candidates = list(session.scalars(pipeline._candidate_query(scenario)))
    run = DecisionRun(
        run_code=f"synthetic-run-{scenario.id}-{number}",
        scenario_id=scenario.id,
        scenario_version=scenario.scenario_version,
        policy_id=policy.id,
        policy_version=policy.policy_version,
        mapping_cutoff=at,
        evidence_cutoff=at,
        price_cutoff=at,
        generated_at=at,
        status=run_status,
        candidate_count=1,
        eligible_count=0,
        blocked_count=1,
        review_count=0,
        warning_count=1,
        content_hash=pipeline._dependency_fingerprint(session, scenario, policy, candidates),
    )
    session.add(run)
    session.flush()
    if not with_result:
        return run, None
    result = CandidateDecisionResult(
        decision_run_id=run.id,
        mapping_candidate_id=mapping.id,
        provider_id=mapping.target_provider_id,
        entity_type=mapping.target_entity_type,
        entity_id=mapping.target_entity_id,
        decision_status=decision_status,
        business_fit_score=Decimal("0.1234"),
        confidence_level="insufficient",
        hard_block_count=1,
        warning_count=1,
        explanation=f"Synthetic immutable explanation {number}",
        missing_information=[{"synthetic": "missing official evidence"}],
        assumptions=["Synthetic only"],
        valid_from=at,
        review_status="machine_generated",
        output_level="internal_only",
        customer_eligible=False,
    )
    session.add(result)
    session.flush()
    return run, result


def assignment(session, result, *, suffix="one", state="blocked_by_deterministic_check"):
    precheck = ModelReviewRun(
        run_code=f"synthetic-precheck-{result.id}-{suffix}",
        policy_version="synthetic-v1",
        reviewer_model="deterministic_evidence_precheck",
        input_fingerprint="a" * 64,
        reviewed_at=datetime.now(UTC),
        summary_json={"synthetic": True},
    )
    session.add(precheck)
    session.flush()
    finding = ModelReviewFinding(
        run_id=precheck.id,
        subject_type="candidate_decision_result",
        subject_id=result.id,
        verdict="blocked",
        reason_code="synthetic_missing_evidence",
        rationale="Synthetic only",
        evidence_ids=[],
        input_hash="b" * 64,
    )
    session.add(finding)
    session.flush()
    row = ModelReviewAssignment(
        precheck_run_id=precheck.id,
        precheck_finding_id=finding.id,
        target_type=finding.subject_type,
        target_id=result.id,
        input_hash=finding.input_hash,
        prior_review_status=result.review_status,
        review_state=state,
        evidence_ids=[],
    )
    session.add(row)
    session.flush()
    session.add(
        ModelReviewAuditEvent(
            assignment_id=row.id,
            event_code=f"synthetic-initial-{row.id}",
            previous_status=None,
            new_status=state,
            source="deterministic_precheck_migration",
            model_id=None,
            reason="synthetic missing evidence",
            affected_records=[{"target_type": finding.subject_type, "target_id": result.id}],
            downstream_rebuild_required=False,
            timestamp=datetime.now(UTC),
        )
    )
    session.flush()
    return row


def seed(session):
    fixture = load_synthetic_fixture(session)
    product = fixture["product"]
    rule = MappingRuleSet(
        rule_set_code="synthetic_supersession",
        rule_set_version="v1",
        mapping_level="product",
        category="compute",
        market_mode="domestic",
        status="active",
    )
    session.add(rule)
    session.flush()
    mapping = MappingCandidate(
        mapping_level="product",
        source_provider_id=product.provider_id,
        source_entity_type="product",
        source_entity_id=product.id,
        target_provider_id=product.provider_id,
        target_entity_type="product",
        target_entity_id=product.id,
        relationship_type="same_service_class",
        candidate_status="candidate",
        rule_set_id=rule.id,
        explanation="Synthetic",
        generated_at=datetime.now(UTC),
        review_status="pending_review",
    )
    policy = ScoringPolicy(
        policy_code="synthetic_supersession",
        policy_version="v1",
        scenario_type="compute_general",
        dimension_weights={},
        missing_data_policy={},
        confidence_policy={},
        thresholds={},
        status="active",
    )
    session.add_all([mapping, policy])
    session.flush()
    scenario = DecisionScenario(
        scenario_code="synthetic_supersession",
        scenario_version="v1",
        name="Synthetic historical scenario",
        scenario_type="compute_general",
        market_mode="domestic",
        workload_profile={"category": "compute", "cost_required": False},
        scoring_policy_id=policy.id,
        status="active",
    )
    session.add(scenario)
    session.flush()
    _, old = add_run(session, scenario, mapping, 1)
    _, newer = add_run(session, scenario, mapping, 2, decision_status="requires_review")
    old_assignment = assignment(session, old)
    session.commit()
    return scenario, mapping, old, newer, old_assignment


@pytest.fixture
def history(session):
    return seed(session)


def plan_for(session, result):
    return plan_decision_supersession(session, result_ids=[result.id])


def test_read_only_plan_binds_both_subjects_and_preserves_missing_evidence(session, history):
    _, _, old, new, review = history
    plan = plan_for(session, old)
    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.old_snapshot["decision"]["id"] == old.id
    assert item.new_snapshot["decision"]["id"] == new.id
    assert item.old_snapshot["decision"]["missing_information"] == old.missing_information
    assert item.assignments[0]["assignment"]["review_state"] == review.review_state
    assert DecisionSupersessionPlan.model_validate_json(plan.model_dump_json()) == plan
    dry = apply_decision_supersession(session, plan)
    assert dry["would_supersede"] == 1 and dry["superseded"] == 0
    assert dry["approvals_granted"] == 0
    assert old.decision_status == "blocked" and old.superseded_by_id is None
    assert session.scalar(select(func.count()).select_from(ModelReviewAuditEvent)) == 1
    assert not session.new and not session.dirty


@pytest.mark.parametrize(
    "status",
    [
        "blocked",
        "insufficient_evidence",
        "incomplete_cost",
        "requires_review",
        "stale_data",
        "invalid_mapping",
        "eligible",
        "conditionally_eligible",
    ],
)
def test_successor_need_not_be_approved_or_eligible(session, history, status):
    _, _, old, new, review = history
    new.decision_status = status
    old.customer_eligible = True
    old.review_status = "internally_approved"
    session.commit()
    plan = plan_for(session, old)
    report = apply_decision_supersession(session, plan, apply=True)
    assert report["superseded"] == report["audit_events_created"] == 1
    assert old.decision_status == review.review_state == "superseded"
    assert old.superseded_by_id == new.id and old.valid_to is not None
    assert old.review_status == "internally_approved"
    assert not old.customer_eligible and not new.customer_eligible
    assert new.decision_status == status and new.review_status == "machine_generated"
    assert old.explanation == "Synthetic immutable explanation 1"
    assert old.business_fit_score == Decimal("0.1234") and old.missing_information
    audit = session.scalar(
        select(ModelReviewAuditEvent).where(
            ModelReviewAuditEvent.source == "deterministic_supersession"
        )
    )
    assert audit.model_id is None and audit.previous_status == "blocked_by_deterministic_check"
    assert audit.new_status == "superseded" and audit.downstream_rebuild_required
    assert audit.affected_records[0]["successor_id"] == new.id
    session.commit()
    repeat = apply_decision_supersession(session, plan, apply=True)
    assert repeat["already_applied"] == 1 and repeat["audit_events_created"] == 0
    assert session.scalar(select(func.count()).select_from(ModelReviewAuditEvent)) == 2


def test_caller_rollback_restores_decision_assignment_and_audit(session, history):
    _, _, old, _, review = history
    plan = plan_for(session, old)
    apply_decision_supersession(session, plan, apply=True)
    session.rollback()
    assert old.decision_status == "blocked" and old.valid_to is None
    assert review.review_state == "blocked_by_deterministic_check"
    assert session.scalar(select(func.count()).select_from(ModelReviewAuditEvent)) == 1


def test_all_old_assignments_get_events_and_history_is_retained(session, history):
    _, _, old, _, _ = history
    other = assignment(session, old, suffix="two", state="model_inconclusive")
    session.commit()
    plan = plan_for(session, old)
    report = apply_decision_supersession(session, plan, apply=True)
    assert report["audit_events_created"] == 2 and other.review_state == "superseded"
    assert session.scalar(select(func.count()).select_from(ModelReviewFinding)) == 2
    assert session.scalar(select(func.count()).select_from(ModelReviewAuditEvent)) == 4


@pytest.mark.parametrize(
    "mutation",
    [
        "old_facts",
        "new_facts",
        "old_state",
        "assignment",
        "new_assignment",
        "finding",
        "audit",
        "new_run",
        "dependency",
        "new_expired",
    ],
)
def test_changed_plan_inputs_fail_without_partial_changes(session, history, mutation):
    scenario, mapping, old, new, review = history
    plan = plan_for(session, old)
    if mutation == "old_facts":
        old.explanation += " changed"
    elif mutation == "new_facts":
        new.explanation += " changed"
    elif mutation == "old_state":
        old.review_status = "rejected"
    elif mutation == "assignment":
        review.review_state = "model_review_in_progress"
    elif mutation == "new_assignment":
        assignment(session, new)
    elif mutation == "finding":
        review.precheck_finding.rationale += " changed"
    elif mutation == "audit":
        session.scalar(select(ModelReviewAuditEvent)).reason += " changed"
    elif mutation == "new_run":
        add_run(session, scenario, mapping, 3)
    elif mutation == "dependency":
        scenario.technical_requirements = {"synthetic": "new requirement"}
    else:
        new.valid_to = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    with pytest.raises(SupersessionConflict):
        apply_decision_supersession(session, plan, apply=True)
    session.rollback()
    assert old.superseded_by_id is None
    assert (
        session.scalar(
            select(func.count())
            .select_from(ModelReviewAuditEvent)
            .where(ModelReviewAuditEvent.source == "deterministic_supersession")
        )
        == 0
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("no_result", "no_concrete_successor"),
        ("latest_old_version", "newest_run_not_current"),
        ("stale_dependencies", "newest_run_dependencies_outdated"),
        ("new_expired", "successor_not_current"),
        ("old_expired", "already_expired"),
        ("wrong_target", "successor_target_identity_mismatch"),
        ("assignment_corrupt", "assignment_precheck_integrity_mismatch"),
        ("assignment_superseded", "assignment_already_superseded_conflict"),
    ],
)
def test_planner_reports_exclusions_instead_of_inventing_successors(
    session, history, mutation, reason
):
    scenario, mapping, old, new, review = history
    if mutation == "no_result":
        add_run(session, scenario, mapping, 3, with_result=False)
    elif mutation == "latest_old_version":
        new.decision_run.policy_version = "obsolete"
    elif mutation == "stale_dependencies":
        new.decision_run.content_hash = "0" * 64
    elif mutation == "new_expired":
        new.valid_to = datetime.now(UTC) - timedelta(seconds=1)
    elif mutation == "old_expired":
        old.valid_to = datetime.now(UTC) - timedelta(seconds=1)
    elif mutation == "wrong_target":
        new.entity_id += 99
    elif mutation == "assignment_corrupt":
        review.input_hash = "c" * 64
    else:
        review.review_state = "superseded"
    session.commit()
    plan = plan_for(session, old)
    assert not plan.items and plan.skipped[0]["reason"] == reason
    assert old.decision_status == "blocked"


def test_never_supersede_newer_by_older_or_across_scenarios(session, history):
    scenario, mapping, old, new, _ = history
    plan = plan_for(session, new)
    assert not plan.items and plan.skipped[0]["reason"] == "no_newer_eligible_run"
    other = DecisionScenario(
        scenario_code="synthetic_other",
        scenario_version="v1",
        name="Other scenario",
        scenario_type=scenario.scenario_type,
        market_mode="domestic",
        workload_profile=scenario.workload_profile,
        scoring_policy_id=scenario.scoring_policy_id,
        status="active",
    )
    session.add(other)
    session.flush()
    add_run(session, other, mapping, 3)
    new.decision_run.status = "failed"
    session.commit()
    assert not plan_for(session, old).items


def test_missing_assignment_is_reported_and_not_fabricated(session, history):
    scenario, mapping, _, new, _ = history
    add_run(session, scenario, mapping, 3)
    session.commit()
    plan = plan_for(session, new)
    assert not plan.items and plan.skipped[0]["reason"] == "missing_review_assignment"
    assert session.scalar(select(func.count()).select_from(ModelReviewAssignment)) == 1


def test_partial_run_usable_but_failed_and_dry_runs_are_not_successors(session, history):
    scenario, mapping, old, new, _ = history
    new.decision_run.status = "partial"
    add_run(session, scenario, mapping, 3, run_status="failed")
    add_run(session, scenario, mapping, 4, run_status="dry_run")
    session.commit()
    assert plan_for(session, old).items[0].new_snapshot["decision"]["id"] == new.id


def test_all_items_are_preflighted_before_any_apply(session, history):
    scenario, mapping, old, new, _ = history
    assignment(session, new)
    _, latest = add_run(session, scenario, mapping, 3)
    session.commit()
    plan = plan_decision_supersession(session, result_ids=[old.id, new.id])
    assert len(plan.items) == 2
    assert {item.new_snapshot["decision"]["id"] for item in plan.items} == {latest.id}
    new.explanation = "Synthetic edit after planning"
    session.commit()
    with pytest.raises(SupersessionConflict):
        apply_decision_supersession(session, plan, apply=True)
    session.rollback()
    assert old.decision_status == "blocked" and old.superseded_by_id is None


def test_mid_apply_failure_rolls_back_its_savepoint(session, history, monkeypatch):
    _, _, old, _, review = history
    plan = plan_for(session, old)
    original = supersession._write_item

    def fail_after_write(*args):
        original(*args)
        raise RuntimeError("synthetic failure after SQL updates")

    monkeypatch.setattr(supersession, "_write_item", fail_after_write)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        apply_decision_supersession(session, plan, apply=True)
    session.commit()
    assert old.decision_status == "blocked" and old.valid_to is None
    assert review.review_state == "blocked_by_deterministic_check"
    assert session.scalar(select(func.count()).select_from(ModelReviewAuditEvent)) == 1


def test_plan_tampering_and_dirty_session_are_rejected(session, history):
    _, _, old, _, _ = history
    plan = plan_for(session, old)
    data = plan.model_dump()
    data["items"][0]["old_snapshot"]["decision"]["explanation"] = "fabricated"
    with pytest.raises(ValueError):
        DecisionSupersessionPlan.model_validate(data)
    old.explanation = "unsaved edit"
    with pytest.raises(SupersessionConflict, match="clean"):
        apply_decision_supersession(session, plan)


def test_concurrent_sqlite_writers_fail_closed_then_retry_idempotently(tmp_path):
    db = create_engine(
        f"sqlite:///{tmp_path / 'synthetic-concurrency.sqlite'}", connect_args={"timeout": 0.1}
    )

    @event.listens_for(db, "connect")
    def enable_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(db)
    with Session(db) as first, Session(db) as second:
        _, _, old, _, _ = seed(first)
        plan = plan_for(first, old)
        first.rollback()
        apply_decision_supersession(first, plan, apply=True)
        with pytest.raises(OperationalError, match="locked"):
            apply_decision_supersession(second, plan, apply=True)
        second.rollback()
        first.commit()
        retried = apply_decision_supersession(second, plan, apply=True)
        assert retried["already_applied"] == 1 and retried["audit_events_created"] == 0
        second.commit()
    db.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "human_review"),
        ("model_id", "synthetic-model"),
        ("new_status", "model_approved"),
        ("affected_records", []),
        ("downstream_rebuild_required", False),
    ],
)
def test_changed_audit_receipt_never_counts_as_idempotent_success(session, history, field, value):
    _, _, old, _, _ = history
    plan = plan_for(session, old)
    apply_decision_supersession(session, plan, apply=True)
    session.commit()
    audit = session.scalar(
        select(ModelReviewAuditEvent).where(
            ModelReviewAuditEvent.source == "deterministic_supersession"
        )
    )
    setattr(audit, field, value)
    session.commit()
    with pytest.raises(SupersessionConflict, match="audit_receipt_changed"):
        apply_decision_supersession(session, plan, apply=True)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(ModelReviewAuditEvent)) == 2


def test_cannot_rehash_plan_to_supersede_newer_with_older(session, history):
    _, _, old, _, _ = history
    plan = plan_for(session, old)
    item = plan.items[0].model_dump()
    item["old_snapshot"], item["new_snapshot"] = item["new_snapshot"], item["old_snapshot"]
    item["old_hash"], item["new_hash"] = item["new_hash"], item["old_hash"]
    with pytest.raises(ValueError, match="higher run"):
        supersession.SupersessionItem.model_validate(item)


def test_no_successor_with_a_different_mapping_candidate(session, history):
    scenario, mapping, old, new, _ = history
    other_rule = MappingRuleSet(
        rule_set_code="synthetic_distinct_mapping",
        rule_set_version="v1",
        mapping_level="product",
        category="compute",
        market_mode="domestic",
        status="active",
    )
    session.add(other_rule)
    session.flush()
    other = MappingCandidate(
        mapping_level="product",
        source_provider_id=mapping.source_provider_id,
        source_entity_type="product",
        source_entity_id=mapping.source_entity_id,
        target_provider_id=mapping.target_provider_id,
        target_entity_type="product",
        target_entity_id=mapping.target_entity_id,
        relationship_type="close_alternative",
        candidate_status="candidate",
        rule_set_id=other_rule.id,
        explanation="Synthetic distinct mapping",
        generated_at=datetime.now(UTC),
        review_status="pending_review",
    )
    session.add(other)
    session.flush()
    new.mapping_candidate_id = other.id
    new.decision_run.content_hash = pipeline._dependency_fingerprint(
        session,
        scenario,
        scenario.scoring_policy,
        list(session.scalars(pipeline._candidate_query(scenario))),
    )
    session.commit()
    plan = plan_for(session, old)
    assert not plan.items and plan.skipped[0]["reason"] == "no_concrete_successor"


def test_bounded_plan_reports_limit_missing_and_already_historical(session, history):
    scenario, mapping, old, new, _ = history
    assignment(session, new)
    add_run(session, scenario, mapping, 3)
    session.commit()
    plan = plan_decision_supersession(session, result_ids=[old.id, new.id, 999999], limit=1)
    assert len(plan.items) == 1
    report = apply_decision_supersession(session, plan, apply=True)
    assert report["skip_reasons"] == {"missing_result": 1, "plan_limit_reached": 1}
    session.commit()
    again = plan_for(session, old)
    assert not again.items and again.skipped[0]["reason"] == "already_historical"
    assert session.scalar(select(func.count()).select_from(CandidateDecisionResult)) == 3
    for limit in (0, 1001):
        with pytest.raises(ValueError, match="limit"):
            plan_decision_supersession(session, limit=limit)


def test_apply_rejects_future_plan_without_writes(session, history):
    _, _, old, _, _ = history
    plan = plan_for(session, old)
    with pytest.raises(SupersessionConflict, match="plan_from_future"):
        apply_decision_supersession(
            session,
            plan,
            apply=True,
            now=datetime.fromisoformat(plan.planned_at) - timedelta(seconds=1),
        )
    assert old.decision_status == "blocked"
