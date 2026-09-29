from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from cloud_expert.database.models.decision import DecisionRun, DecisionScenario, ScenarioRequirement
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.decision.pipeline import (
    _dimension_inputs,
    _status_from_candidate,
    create_from_config,
    run_decision_engine,
)
from cloud_expert.decision.requirements import (
    compare_value,
    evaluate_requirement,
    evaluate_scenario_requirements,
)


def requirement(**kwargs):
    values = {
        "requirement_code": "architecture",
        "requirement_type": "technical",
        "required_value": {"architecture": "x86"},
        "operator": "equals",
        "priority": "mandatory",
        "is_mandatory": True,
        "missing_data_policy": "requires_review",
    }
    values.update(kwargs)
    return ScenarioRequirement(**values)


def test_undeclared_nonhardware_requirements_still_require_evidence(session):
    scenario = DecisionScenario(
        compliance_requirements={"certification": "synthetic-cert"},
        data_residency_requirements={"data_country": "CN"},
        operational_requirements={"managed_operations": True},
        migration_requirements={"maximum_downtime_minutes": 10},
    )
    candidate = MappingCandidate(target_entity_type="product", target_entity_id=999)
    outcomes = evaluate_scenario_requirements(session, scenario, candidate, None)
    assert {item.dimension for item in outcomes} == {
        "compliance_fit",
        "regional_fit",
        "operability_fit",
        "migration_fit",
    }
    assert all(item.status == "missing_data" and item.requires_review for item in outcomes)


def test_same_key_in_different_requirement_types_is_not_suppressed(session):
    scenario = DecisionScenario(
        requirements=[requirement(required_value={"certification": "synthetic-cert"})],
        compliance_requirements={"certification": "synthetic-cert"},
    )
    candidate = MappingCandidate(target_entity_type="product", target_entity_id=999)
    outcomes = evaluate_scenario_requirements(session, scenario, candidate, None)
    assert len(outcomes) == 2
    assert {item.dimension for item in outcomes} == {"technical_fit", "compliance_fit"}


@pytest.mark.parametrize(
    "observed,expected,operator,result",
    [
        ("x86", "arm", "equals", False),
        (Decimal("4"), 4, "equals", True),
        (True, 1, "equals", False),
        (None, "x86", "equals", None),
        ("x86", "x86", "unsupported", None),
        (4, 2, "greater_than", True),
        (4, [3, 5], "between", True),
        (4, [1, 2, 3], "between", None),
        ("x86", ["x86", "arm"], "in", True),
        ("x86", "x86", "in", None),
        ("NaN", 3, "greater_than", None),
    ],
)
def test_comparison_operators(observed, expected, operator, result):
    assert compare_value(observed, expected, operator) is result


def test_requirement_missing_fact_is_review_not_failure():
    result = evaluate_requirement(requirement(), {}, ())
    assert result.status == "missing_data" and result.requires_review and not result.hard_block


def test_conflicting_architecture_blocks():
    result = evaluate_requirement(requirement(), {"architecture": "arm"}, (1,))
    assert result.status == "fail" and result.hard_block


def test_unproven_fact_never_passes():
    result = evaluate_requirement(
        requirement(missing_data_policy="block"), {"architecture": "x86"}, ()
    )
    assert result.status == "missing_data" and result.hard_block


def test_scoped_model_approval_keeps_technical_requirement_gate():
    candidate = MappingCandidate(candidate_status="approved", review_status="pending_review")
    package = EvidencePackage(evidence_completeness=1, customer_eligible=False)
    scenario = DecisionScenario(workload_profile={"cost_required": False})
    args = {
        "candidate": candidate,
        "package": package,
        "tco": None,
        "hard_blocks": [],
        "scenario": scenario,
        "scoped_model_approval": True,
    }
    assert _status_from_candidate(**args, requirements_need_review=True) == "requires_review"
    assert _status_from_candidate(**args) == "conditionally_eligible"
    assert candidate.review_status == "pending_review"


def test_category_scope_is_not_technical_or_migration_score():
    candidate = MappingCandidate(
        mapping_level="product", normalized_score=Decimal("1"), review_status="pending_review"
    )
    dimensions = _dimension_inputs(
        candidate=candidate,
        package=None,
        tco=TCOResult(completeness_status="complete", freshness_status="fresh"),
        comparison_counts=Counter({"comparable": 20}),
        scoped_model_approval=True,
    )
    for key in (
        "technical_fit",
        "availability_fit",
        "regional_fit",
        "reliability_fit",
        "migration_fit",
        "cost_fit",
        "evidence_quality",
        "data_freshness",
    ):
        assert dimensions[key][0] is None
    assert dimensions["review_readiness"][0] == Decimal("1")


def test_dry_run_does_not_leave_persisted_run(session):
    scenario = create_from_config(session, Path("config/decision/scenarios/general_compute.yaml"))
    summary = run_decision_engine(session, scenario.scenario_code, dry_run=True)
    assert summary.status == "dry_run"
    assert session.scalar(select(func.count()).select_from(DecisionRun)) == 0
