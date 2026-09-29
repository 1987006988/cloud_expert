"""Synthetic, transient ORM tests; no session, engine, database, or real facts.

Fail-closed assertions are regression requirements, not descriptions of known
bugs. Keep them failing until the owning agent fixes the business implementation.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect

from cloud_expert.database.enums import TCOCompletenessStatus
from cloud_expert.database.models.decision import ScoringRule
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.decision import policy_rules, rule_registry

MAPPING = "week7_mapping_candidate"
PACKAGE = "week8_evidence_package"
TCO = "week9_tco_result"
SOURCES = (MAPPING, PACKAGE, TCO)
EVIDENCE_IDS = (900001, 900002)
INPUT_FIELDS = {
    MAPPING: ("candidate", "normalized_score"),
    PACKAGE: ("package", "evidence_completeness"),
    TCO: ("tco", "completeness_status"),
}


def _rule(source: str = MAPPING, **overrides: Any) -> ScoringRule:
    values: dict[str, Any] = {
        "id": 900010,
        "policy_id": 900011,
        "rule_code": "synthetic_policy_rule",
        "rule_version": "synthetic.v1",
        "dimension": "technical_fit",
        "operator": "greater_than_or_equal",
        "expected_value": {"minimum": "0.5000"},
        "minimum_score": Decimal("0.0000"),
        "maximum_score": Decimal("1.0000"),
        "score_function": "ratio_fit",
        "conditions": {"source": source},
        "evidence_requirement": {"evidence_package_required": True},
        "priority": "mandatory",
        "missing_data_policy": "block",
        "status": "active",
    }
    if source == PACKAGE:
        values.update(
            dimension="evidence_quality",
            operator="evidence_at_least",
            score_function="evidence_fit",
        )
    elif source == TCO:
        values.update(
            dimension="cost_fit",
            operator="equals",
            expected_value={"completeness_status": "complete"},
            score_function="exact_match",
            evidence_requirement={"price_snapshot_required": True},
        )
    values.update(overrides)
    return ScoringRule(**values)


@pytest.fixture
def subjects() -> dict[str, Any]:
    return {
        "candidate": MappingCandidate(
            id=900020,
            mapping_level="sku",
            source_entity_type="sku",
            source_entity_id=900021,
            target_entity_type="sku",
            target_entity_id=900022,
            normalized_score=Decimal("0.7500"),
            explanation="SYNTHETIC mapping; no cloud capability assertion.",
        ),
        "package": EvidencePackage(
            id=900030,
            package_code="synthetic_policy_package",
            mapping_candidate_id=900020,
            evidence_completeness=Decimal("0.7500"),
            customer_eligible=False,
        ),
        "tco": TCOResult(id=900040, completeness_status="complete"),
    }


def _set_observed(subjects: dict[str, Any], source: str, value: Any) -> None:
    entity, field = INPUT_FIELDS[source]
    setattr(subjects[entity], field, value)


def _evaluate(
    rule: ScoringRule, subjects: dict[str, Any], evidence_ids: tuple[int, ...] = EVIDENCE_IDS
) -> policy_rules.PolicyOutcome:
    return policy_rules.evaluate_policy_rule(rule, **subjects, evidence_ids=evidence_ids)


def _assert_missing(
    result: policy_rules.PolicyOutcome, *, hard_block: bool = True, requires_review: bool = True
) -> None:
    assert result.status == "missing_data", result
    assert result.score is None, "Unknown/unsupported inputs must not retain a numeric score"
    assert result.hard_block is hard_block, result
    assert result.requires_review is requires_review, result
    assert result.reason == "synthetic_policy_rule:missing_data"


@pytest.mark.parametrize(
    "source,value,status,score,observed",
    [
        (MAPPING, Decimal("0.7500"), "pass", "1.0000", {"normalized_mapping_score": "0.7500"}),
        (MAPPING, Decimal("0.5000"), "pass", "1.0000", {"normalized_mapping_score": "0.5000"}),
        (MAPPING, Decimal("0.2500"), "fail", "0.5000", {"normalized_mapping_score": "0.2500"}),
        (MAPPING, Decimal("0.0000"), "fail", "0.0000", {"normalized_mapping_score": "0.0000"}),
        (PACKAGE, Decimal("0.7500"), "pass", "1.0000", {"evidence_completeness": "0.7500"}),
        (PACKAGE, Decimal("0.5000"), "pass", "1.0000", {"evidence_completeness": "0.5000"}),
        (PACKAGE, Decimal("0.2500"), "fail", "0.5000", {"evidence_completeness": "0.2500"}),
        (PACKAGE, Decimal("0.0000"), "fail", "0.0000", {"evidence_completeness": "0.0000"}),
        (
            TCO,
            "complete",
            "pass",
            "1.0000",
            {"completeness_status": "complete", "tco_result_id": 900040},
        ),
        (
            TCO,
            "partial",
            "fail",
            "0.0000",
            {"completeness_status": "partial", "tco_result_id": 900040},
        ),
    ],
)
def test_registered_sources_return_real_scores_and_correct_pass_fail(
    subjects: dict[str, Any],
    source: str,
    value: Any,
    status: str,
    score: str,
    observed: dict[str, Any],
) -> None:
    rule = _rule(source)
    _set_observed(subjects, source, value)
    result = _evaluate(rule, subjects)
    assert result.rule_id == rule.id
    assert result.observed == observed
    assert result.expected == rule.expected_value
    assert result.evidence_ids == EVIDENCE_IDS
    assert result.status == status
    assert isinstance(result.score, Decimal)
    assert result.score == Decimal(score)
    assert result.hard_block is (status == "fail")
    assert result.requires_review is False
    assert result.reason == (None if status == "pass" else "synthetic_policy_rule:fail")


@pytest.mark.parametrize("source", SOURCES)
def test_other_registered_inputs_cannot_change_the_selected_source(
    subjects: dict[str, Any], source: str
) -> None:
    for other in SOURCES:
        if other != source:
            _set_observed(subjects, other, None)
    assert _evaluate(_rule(source), subjects).status == "pass"


@pytest.mark.parametrize(
    "level", ["category", "product", "product_family", "service_tier", "unknown"]
)
def test_non_sku_mapping_score_cannot_establish_sku_fit(
    subjects: dict[str, Any], level: str
) -> None:
    subjects["candidate"].mapping_level = level
    subjects["candidate"].target_entity_type = "product"
    subjects["candidate"].normalized_score = Decimal("1.0000")
    result = _evaluate(_rule(MAPPING), subjects)
    _assert_missing(result)
    assert result.observed == {}


@pytest.mark.parametrize("source", [PACKAGE, TCO])
def test_category_scope_does_not_hide_separately_registered_quality_or_cost_inputs(
    subjects: dict[str, Any], source: str
) -> None:
    subjects["candidate"].mapping_level = "category"
    result = _evaluate(_rule(source), subjects)
    assert result.status == "pass"
    assert "normalized_mapping_score" not in result.observed


@pytest.mark.parametrize("source", SOURCES)
def test_missing_observed_value_is_unknown_not_zero(subjects: dict[str, Any], source: str) -> None:
    _set_observed(subjects, source, None)
    _assert_missing(_evaluate(_rule(source), subjects))


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("expected", [None, {}, {"unrecognized_bound": "synthetic"}])
def test_missing_bound_is_unknown_not_zero(
    subjects: dict[str, Any], source: str, expected: dict[str, Any] | None
) -> None:
    _assert_missing(_evaluate(_rule(source, expected_value=expected), subjects))


@pytest.mark.parametrize("source,entity", [(PACKAGE, "package"), (TCO, "tco")])
def test_missing_source_object_cannot_fall_back_to_another_source(
    subjects: dict[str, Any], source: str, entity: str
) -> None:
    subjects[entity] = None
    result = _evaluate(_rule(source), subjects)
    _assert_missing(result)
    assert result.observed == {}


@pytest.mark.parametrize("conditions", [None, {}, {"source": "synthetic_unregistered"}])
def test_unregistered_or_missing_source_is_fail_closed(
    subjects: dict[str, Any], conditions: dict[str, Any] | None
) -> None:
    _assert_missing(_evaluate(_rule(conditions=conditions), subjects))


@pytest.mark.parametrize("source", SOURCES)
def test_missing_evidence_never_calls_scorer_or_approves(
    subjects: dict[str, Any], source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    lookup = Mock(side_effect=AssertionError("Scoring without evidence is forbidden"))
    monkeypatch.setattr(policy_rules, "get_score_function", lookup)
    result = _evaluate(_rule(source), subjects, evidence_ids=())
    _assert_missing(result)
    assert result.evidence_ids == ()
    lookup.assert_not_called()


@pytest.mark.parametrize("priority", ["mandatory", "critical"])
@pytest.mark.parametrize("missing_policy", ["block", "requires_review", "exclude_dimension"])
def test_mandatory_failed_comparison_blocks_regardless_of_missing_policy(
    subjects: dict[str, Any], priority: str, missing_policy: str
) -> None:
    subjects["candidate"].normalized_score = Decimal("0.2500")
    result = _evaluate(_rule(priority=priority, missing_data_policy=missing_policy), subjects)
    assert result.status == "fail" and result.hard_block
    assert result.score == Decimal("0.5000")
    assert not result.requires_review


@pytest.mark.parametrize("priority", ["mandatory", "critical"])
@pytest.mark.parametrize("missing_policy,hard_block", [("block", True), ("requires_review", False)])
def test_mandatory_missing_input_obeys_explicit_block_or_review_policy(
    subjects: dict[str, Any], priority: str, missing_policy: str, hard_block: bool
) -> None:
    subjects["candidate"].normalized_score = None
    _assert_missing(
        _evaluate(_rule(priority=priority, missing_data_policy=missing_policy), subjects),
        hard_block=hard_block,
    )


def test_nonmandatory_failure_does_not_invent_a_hard_block(subjects: dict[str, Any]) -> None:
    subjects["candidate"].normalized_score = Decimal("0.2500")
    result = _evaluate(_rule(priority="high"), subjects)
    assert result.status == "fail"
    assert not result.hard_block and not result.requires_review


@pytest.mark.parametrize("policy,review", [("requires_review", True), ("exclude_dimension", False)])
def test_optional_missing_data_retains_configured_review_semantics(
    subjects: dict[str, Any], policy: str, review: bool
) -> None:
    subjects["candidate"].normalized_score = None
    _assert_missing(
        _evaluate(_rule(priority="high", missing_data_policy=policy), subjects),
        hard_block=False,
        requires_review=review,
    )


@pytest.mark.parametrize("name", ["synthetic_unregistered", "custom_registered"])
def test_missing_registry_function_is_unknown_not_automatic_pass(
    subjects: dict[str, Any], name: str
) -> None:
    _assert_missing(_evaluate(_rule(score_function=name), subjects))


@pytest.mark.parametrize(
    "value", ["unknown", "not-a-number", [], {}, True, Decimal("NaN"), Decimal("Infinity")]
)
def test_numeric_input_type_mismatch_is_unknown(subjects: dict[str, Any], value: Any) -> None:
    subjects["candidate"].normalized_score = value
    _assert_missing(_evaluate(_rule(), subjects))


def test_numeric_score_function_cannot_consume_tco_status_string(subjects: dict[str, Any]) -> None:
    _assert_missing(_evaluate(_rule(TCO, score_function="ratio_fit"), subjects))


def test_unknown_tco_status_is_not_a_known_zero_score(subjects: dict[str, Any]) -> None:
    subjects["tco"].completeness_status = "unknown"
    _assert_missing(_evaluate(_rule(TCO), subjects))


@pytest.mark.parametrize("source", [[MAPPING], {"name": MAPPING}])
def test_non_scalar_source_condition_returns_missing_not_an_exception(
    subjects: dict[str, Any], source: Any
) -> None:
    _assert_missing(_evaluate(_rule(conditions={"source": source}), subjects))


@pytest.mark.parametrize("status", [["complete"], {"status": "complete"}])
def test_non_scalar_tco_status_returns_missing_not_an_exception(
    subjects: dict[str, Any], status: Any
) -> None:
    subjects["tco"].completeness_status = status
    _assert_missing(_evaluate(_rule(TCO), subjects))


def test_unregistered_missing_tco_status_is_not_a_known_zero_score(
    subjects: dict[str, Any],
) -> None:
    assert "missing" not in TCOCompletenessStatus.values()
    subjects["tco"].completeness_status = "missing"
    _assert_missing(_evaluate(_rule(TCO), subjects))


@pytest.mark.parametrize(
    "minimum,maximum",
    [(Decimal("0.1"), Decimal("1")), (Decimal("0"), Decimal("0.9")), (None, None)],
    ids=["raised-minimum", "reduced-maximum", "missing-bounds"],
)
def test_unsupported_score_bounds_remain_unknown(
    subjects: dict[str, Any], minimum: Decimal | None, maximum: Decimal | None
) -> None:
    assert _evaluate(_rule(), subjects).status == "pass"
    _assert_missing(_evaluate(_rule(minimum_score=minimum, maximum_score=maximum), subjects))


@pytest.mark.parametrize(
    "requirements",
    [
        {"synthetic_unsupported_predicate": True},
        {"evidence_package_required": "true"},
        {"price_snapshot_required": 1},
    ],
    ids=["unknown-predicate", "string-is-not-bool", "integer-is-not-bool"],
)
def test_evidence_requirements_need_supported_boolean_predicates(
    subjects: dict[str, Any], requirements: dict[str, Any]
) -> None:
    _assert_missing(_evaluate(_rule(evidence_requirement=requirements), subjects))


@pytest.mark.parametrize(
    "predicate,entity",
    [("evidence_package_required", "package"), ("price_snapshot_required", "tco")],
)
def test_required_evidence_object_cannot_be_replaced_by_bare_evidence_ids(
    subjects: dict[str, Any], predicate: str, entity: str
) -> None:
    rule = _rule(evidence_requirement={predicate: True})
    assert _evaluate(rule, subjects).status == "pass"
    subjects[entity] = None
    result = _evaluate(rule, subjects)
    assert result.evidence_ids == EVIDENCE_IDS
    _assert_missing(result)


@pytest.mark.parametrize(
    "predicate,entity",
    [("evidence_package_required", "package"), ("price_snapshot_required", "tco")],
)
def test_explicitly_optional_evidence_object_does_not_block_supported_mapping_score(
    subjects: dict[str, Any], predicate: str, entity: str
) -> None:
    subjects[entity] = None
    result = _evaluate(_rule(evidence_requirement={predicate: False}), subjects)
    assert result.status == "pass" and result.score == Decimal("1.0000")
    assert not result.hard_block and not result.requires_review


@pytest.mark.parametrize(
    "error", [ValueError("synthetic"), TypeError("synthetic"), ArithmeticError("synthetic")]
)
def test_registered_scorer_errors_are_fail_closed(
    subjects: dict[str, Any], monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def broken_score(observed: Any, expected: Any) -> Decimal:
        raise error

    monkeypatch.setitem(rule_registry.REGISTRY, "ratio_fit", broken_score)
    _assert_missing(_evaluate(_rule(), subjects))


@pytest.mark.parametrize("invalid_score", ["1.0000", 1, 1.0, True, [], {}])
def test_registry_return_type_mismatch_must_not_approve(
    subjects: dict[str, Any], monkeypatch: pytest.MonkeyPatch, invalid_score: Any
) -> None:
    def wrong_type(observed: Any, expected: Any) -> Any:
        return invalid_score

    monkeypatch.setitem(rule_registry.REGISTRY, "ratio_fit", wrong_type)
    _assert_missing(_evaluate(_rule(), subjects))


@pytest.mark.parametrize(
    "invalid_score", [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"), Decimal("1.1")]
)
def test_registry_return_must_be_a_finite_normalized_score(
    subjects: dict[str, Any], monkeypatch: pytest.MonkeyPatch, invalid_score: Decimal
) -> None:
    def invalid_numeric(observed: Any, expected: Any) -> Decimal:
        return invalid_score

    monkeypatch.setitem(rule_registry.REGISTRY, "ratio_fit", invalid_numeric)
    _assert_missing(_evaluate(_rule(), subjects))


def test_boolean_score_function_cannot_silently_score_numeric_source_as_zero(
    subjects: dict[str, Any],
) -> None:
    _assert_missing(_evaluate(_rule(score_function="boolean_match"), subjects))


@pytest.mark.parametrize("operator", ["synthetic_unsupported", "in", "between"])
def test_unknown_operator_or_wrong_operand_shape_must_not_retain_a_score(
    subjects: dict[str, Any], operator: str
) -> None:
    _assert_missing(_evaluate(_rule(operator=operator), subjects))


@pytest.mark.parametrize("extra", [{"unsupported_predicate": True}, {"mapping_level": "category"}])
def test_unsupported_additional_condition_is_not_silently_ignored(
    subjects: dict[str, Any], extra: dict[str, Any]
) -> None:
    _assert_missing(_evaluate(_rule(conditions={"source": MAPPING, **extra}), subjects))


@pytest.mark.parametrize(
    "source,value,operator,score_function",
    [
        (TCO, "partial", "not_equals", "exact_match"),
        (TCO, "complete", "not_equals", "exact_match"),
        (MAPPING, Decimal("0.7500"), "less_than", "ratio_fit"),
        (MAPPING, Decimal("0.2500"), "less_than", "threshold_fit"),
        (MAPPING, Decimal("0.7500"), "less_than", "threshold_fit"),
    ],
)
def test_conflicting_operator_and_score_function_require_review_not_contradictory_scores(
    subjects: dict[str, Any], source: str, value: Any, operator: str, score_function: str
) -> None:
    _set_observed(subjects, source, value)
    _assert_missing(
        _evaluate(_rule(source, operator=operator, score_function=score_function), subjects)
    )


def test_evaluation_is_read_only_and_keeps_all_objects_transient(subjects: dict[str, Any]) -> None:
    rule = _rule()
    objects = [rule, *subjects.values()]
    before = [
        deepcopy({key: value for key, value in vars(obj).items() if key != "_sa_instance_state"})
        for obj in objects
    ]
    assert _evaluate(rule, subjects).status == "pass"
    for obj, snapshot in zip(objects, before, strict=True):
        assert inspect(obj).transient and inspect(obj).session is None
        assert {
            key: value for key, value in vars(obj).items() if key != "_sa_instance_state"
        } == snapshot
