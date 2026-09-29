"""Synthetic-only arithmetic fixtures; no cloud facts, approvals or database writes."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from cloud_expert.database.enums import DimensionScoreStatus, SensitivityStatus
from cloud_expert.database.models.decision import DecisionSensitivityResult
from cloud_expert.decision.pipeline import _business_fit
from cloud_expert.decision.sensitivity import (
    NumericInput,
    SensitivityPayload,
    analyze_weight_sensitivity,
)

COST = "cost_fit"
TECHNICAL = "technical_fit"
SCORED = DimensionScoreStatus.SCORED.value
WEIGHTS = {COST: Decimal("0.5"), TECHNICAL: Decimal("0.5")}
type Measurements = dict[str, tuple[NumericInput | None, str]]


def _measured(technical: str | None, cost: str | None) -> Measurements:
    return {
        TECHNICAL: (Decimal(technical) if technical is not None else None, SCORED),
        COST: (Decimal(cost) if cost is not None else None, SCORED),
    }


def _crossing_candidates() -> dict[int, Measurements]:
    return {1: _measured("1", "0"), 2: _measured("0.51", "0.51")}


def _crossing_result() -> SensitivityPayload:
    return analyze_weight_sensitivity(
        candidate_dimensions=_crossing_candidates(), weights=WEIGHTS, eligible_candidate_ids=[1, 2]
    )


def test_measured_rank_reversals_have_real_variance_and_auditable_scenarios() -> None:
    result = _crossing_result()
    assert result["ranking_stability"] == "ranking_changed"
    assert result["sensitivity_status"] == SensitivityStatus.HIGHLY_SENSITIVE.value
    assert result["top_candidate_change_count"] == 2
    assert result["critical_assumption_count"] == 2
    # Candidate 1: [0.5, 0.5263, 0.4762, 0.4737, 0.5238]; candidate 2: constant 0.51.
    assert result["score_variance"] == Decimal("0.000252")
    assert result["score_variance"].as_tuple().exponent == -6
    baseline, *scenarios = result["scenarios_tested"]
    assert baseline["scores"] == {"1": "0.5000", "2": "0.5100"}
    assert baseline["ranks"] == {"1": 2, "2": 1}
    assert baseline["tie_sets"] == [[2], [1]]
    assert baseline["score_variance_available"] is True
    assert baseline["variance_candidate_count"] == 2
    assert [(row["dimension"], row["multiplier"]) for row in scenarios] == [
        (COST, "0.9"),
        (COST, "1.1"),
        (TECHNICAL, "0.9"),
        (TECHNICAL, "1.1"),
    ]
    assert [row["scores"]["1"] for row in scenarios] == ["0.5263", "0.4762", "0.4737", "0.5238"]
    assert [row["top_candidate_ids"] for row in scenarios] == [[1], [2], [2], [1]]
    assert scenarios[0]["weights"] == {COST: "0.45", TECHNICAL: "0.5"}
    assert scenarios[3]["weights"] == {COST: "0.5", TECHNICAL: "0.55"}


def test_stable_ranking_does_not_imply_zero_score_variance() -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions={1: _measured("0.9", "0.7"), 2: _measured("0.6", "0.2")},
        weights=WEIGHTS,
        eligible_candidate_ids=[1, 2],
    )
    assert result["ranking_stability"] == "ranking_unchanged"
    assert result["sensitivity_status"] == SensitivityStatus.STABLE.value
    assert result["score_variance"] > 0
    assert result["top_candidate_change_count"] == result["critical_assumption_count"] == 0
    assert all(row["tie_sets"] == [[1], [2]] for row in result["scenarios_tested"])


def test_lower_rank_reversal_is_moderately_sensitive() -> None:
    candidates = {**_crossing_candidates(), 3: _measured("0.9", "0.9")}
    result = analyze_weight_sensitivity(
        candidate_dimensions=candidates, weights=WEIGHTS, eligible_candidate_ids=[1, 2, 3]
    )
    assert result["sensitivity_status"] == SensitivityStatus.MODERATELY_SENSITIVE.value
    assert result["ranking_stability"] == "ranking_changed"
    assert result["top_candidate_change_count"] == 0
    assert result["critical_assumption_count"] == 2
    assert result["scenarios_tested"][1]["tie_sets"] == [[3], [1], [2]]


def test_top_tie_breaking_counts_as_a_change_without_arbitrary_winner() -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions={1: _measured("1", "0"), 2: _measured("0", "1")},
        weights=WEIGHTS,
        eligible_candidate_ids=[2, 1],
        baseline_ranks={1: 1, 2: 1},
    )
    assert result["scenarios_tested"][0]["tie_sets"] == [[1, 2]]
    assert result["scenarios_tested"][0]["top_candidate_ids"] == [1, 2]
    assert result["top_candidate_change_count"] == 4
    assert result["critical_assumption_count"] == 2


def test_top_tie_creation_counts_even_when_previous_leader_remains_in_top_set() -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions={1: _measured("1", "0"), 2: _measured("0.5263", "0.5263")},
        weights=WEIGHTS,
        eligible_candidate_ids=[1, 2],
    )
    assert result["scenarios_tested"][0]["top_candidate_ids"] == [2]
    assert result["scenarios_tested"][1]["top_candidate_ids"] == [1, 2]
    assert result["top_candidate_change_count"] == 1
    assert result["critical_assumption_count"] == 1


def test_dense_ties_are_rounded_to_pipeline_precision_and_can_be_stable() -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions={
            3: _measured("0.2", "0.2"),
            2: _measured("0.8", "0.8"),
            1: _measured("0.80001", "0.80001"),
        },
        weights=WEIGHTS,
        eligible_candidate_ids=[3, 2, 1],
    )
    assert result["sensitivity_status"] == "stable"
    assert result["score_variance"] == Decimal("0.000000")
    assert result["top_candidate_change_count"] == 0
    for row in result["scenarios_tested"]:
        assert row["ranks"] == {"1": 1, "2": 1, "3": 2}
        assert row["tie_sets"] == [[1, 2], [3]]


@pytest.mark.parametrize("count", [0, 1])
def test_fewer_than_two_eligible_candidates_is_indeterminate(count: int) -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions=_crossing_candidates(),
        weights=WEIGHTS,
        eligible_candidate_ids=list(range(1, count + 1)),
    )
    assert result["sensitivity_status"] == "indeterminate"
    assert result["ranking_stability"] == "indeterminate"
    assert result["scenarios_tested"][0]["indeterminate_reasons"] == [
        "fewer_than_two_eligible_candidates"
    ]
    assert result["scenarios_tested"][0]["score_variance_available"] is bool(count)
    assert result["top_candidate_change_count"] == result["critical_assumption_count"] == 0
    assert all(row["ranking_changed"] is None for row in result["scenarios_tested"][1:])


def test_empty_candidate_input_does_not_report_stable() -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions={}, weights=WEIGHTS, eligible_candidate_ids=[]
    )
    assert result["sensitivity_status"] == "indeterminate"
    assert result["score_variance"] == Decimal("0.000000")
    assert all(row["scores"] == {} and row["tie_sets"] == [] for row in result["scenarios_tested"])


@pytest.mark.parametrize("missing", [{}, _measured(None, None)])
def test_unscorable_eligible_candidate_is_not_silently_dropped(missing: Measurements) -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions={**_crossing_candidates(), 3: missing},
        weights=WEIGHTS,
        eligible_candidate_ids=[1, 2, 3],
    )
    assert result["sensitivity_status"] == "indeterminate"
    assert result["scenarios_tested"][0]["unscorable_candidate_ids"] == [3]
    assert result["scenarios_tested"][0]["variance_candidate_count"] == 2
    for row in result["scenarios_tested"]:
        assert row["scores"]["3"] is None
        assert row["ranks"]["3"] is None


@pytest.mark.parametrize("weights", [{}, {COST: Decimal(0), TECHNICAL: Decimal(0)}])
def test_no_positive_weight_means_no_valid_scores_or_perturbations(
    weights: dict[str, Decimal],
) -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions=_crossing_candidates(), weights=weights, eligible_candidate_ids=[1, 2]
    )
    assert result["sensitivity_status"] == "indeterminate"
    assert len(result["scenarios_tested"]) == 1
    baseline = result["scenarios_tested"][0]
    assert "no_positive_weights" in baseline["indeterminate_reasons"]
    assert baseline["scores"] == {"1": None, "2": None}
    assert baseline["score_variance_available"] is False


def test_only_positive_weights_are_perturbed_including_unused_dimensions() -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions=_crossing_candidates(),
        weights={COST: "1", TECHNICAL: "0", "compliance_fit": "0.5"},
        eligible_candidate_ids=[1, 2],
    )
    assert len(result["scenarios_tested"]) == 5
    assert {row["dimension"] for row in result["scenarios_tested"][1:]} == {COST, "compliance_fit"}
    assert result["sensitivity_status"] == "stable"
    for row in result["scenarios_tested"]:
        assert row["scores"] == {"1": "0.0000", "2": "0.5100"}
        assert row["weights"][TECHNICAL] == "0"


@pytest.mark.parametrize("status", ["excluded", "insufficient_evidence"])
def test_excluded_measurements_are_not_zero_imputed_and_remain_in_audit(status: str) -> None:
    candidates = {1: _measured("0.8", "0.1"), 2: _measured("0.6", None)}
    candidates[1][COST] = (Decimal("0.1"), status)
    result = analyze_weight_sensitivity(
        candidate_dimensions=candidates, weights=WEIGHTS, eligible_candidate_ids=[1, 2]
    )
    assert result["sensitivity_status"] == "stable"
    for row in result["scenarios_tested"]:
        assert row["scores"] == {"1": "0.8000", "2": "0.6000"}
    assert result["scenarios_tested"][0]["candidate_dimensions"]["1"][COST] == {
        "score": "0.1",
        "status": status,
    }
    assert result["scenarios_tested"][0]["candidate_dimensions"]["2"][COST]["score"] is None


def test_ineligible_candidates_cannot_affect_ranks_variance_or_status() -> None:
    candidates = {**_crossing_candidates(), 3: _measured("1", "1"), 4: _measured(None, None)}
    candidates[3][COST] = (Decimal(1), DimensionScoreStatus.BLOCKED.value)
    result = analyze_weight_sensitivity(
        candidate_dimensions=candidates, weights=WEIGHTS, eligible_candidate_ids=[1, 2]
    )
    expected = _crossing_result()
    assert {key: value for key, value in result.items() if key != "scenarios_tested"} == {
        key: value for key, value in expected.items() if key != "scenarios_tested"
    }
    for row in result["scenarios_tested"]:
        assert row["scores"]["3"] == "1.0000"
        assert row["scores"]["4"] is None
        assert row["ranks"]["3"] is row["ranks"]["4"] is None
        assert 3 not in row["top_candidate_ids"]


def test_blocked_dimension_prevents_conclusive_sensitivity() -> None:
    candidates = _crossing_candidates()
    candidates[1][COST] = (Decimal(0), DimensionScoreStatus.BLOCKED.value)
    result = analyze_weight_sensitivity(
        candidate_dimensions=candidates, weights=WEIGHTS, eligible_candidate_ids=[1, 2]
    )
    assert result["sensitivity_status"] == "indeterminate"
    assert result["scenarios_tested"][0]["blocked_dimensions"] == [
        {"candidate_id": 1, "dimension": COST}
    ]


@pytest.mark.parametrize("supplied", [{1: 1, 2: 2}, {1: 2}, {1: None, 2: 1}, {1: 2, 2: 1, 3: 3}])
def test_inconsistent_supplied_baseline_is_indeterminate(supplied: dict[int, int | None]) -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions={**_crossing_candidates(), 3: _measured("1", "1")},
        weights=WEIGHTS,
        eligible_candidate_ids=[1, 2],
        baseline_ranks=supplied,
    )
    assert result["sensitivity_status"] == "indeterminate"
    baseline = result["scenarios_tested"][0]
    assert baseline["indeterminate_reasons"] == ["baseline_rank_mismatch"]
    assert baseline["ranks"] == {"1": 2, "2": 1, "3": None}
    assert baseline["supplied_baseline_ranks"] == {
        str(key): value for key, value in supplied.items()
    }


def test_matching_supplied_baseline_uses_real_perturbations() -> None:
    result = analyze_weight_sensitivity(
        candidate_dimensions=_crossing_candidates(),
        weights=WEIGHTS,
        eligible_candidate_ids=[1, 2],
        baseline_ranks={1: 2, 2: 1},
    )
    assert result["sensitivity_status"] == "highly_sensitive"
    assert result["scenarios_tested"][0]["indeterminate_reasons"] == []


def test_decimal_context_order_and_repeated_calls_do_not_change_output_or_inputs() -> None:
    candidates = _crossing_candidates()
    weights = dict(WEIGHTS)
    ranks = {1: 2, 2: 1}
    eligible_ids = [1, 2]
    original = deepcopy((candidates, weights, ranks, eligible_ids))
    expected = analyze_weight_sensitivity(
        candidate_dimensions=candidates,
        weights=weights,
        eligible_candidate_ids=eligible_ids,
        baseline_ranks=ranks,
    )
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_DOWN
        actual = analyze_weight_sensitivity(
            candidate_dimensions={
                key: dict(reversed(list(value.items())))
                for key, value in reversed(list(candidates.items()))
            },
            weights=dict(reversed(list(weights.items()))),
            eligible_candidate_ids=eligible_ids[::-1],
            baseline_ranks=dict(reversed(list(ranks.items()))),
        )
    assert actual == expected
    assert (candidates, weights, ranks, eligible_ids) == original
    expected["scenarios_tested"][0]["candidate_dimensions"]["1"][COST]["score"] = None
    assert (candidates, weights, ranks, eligible_ids) == original


@pytest.mark.parametrize("status", DimensionScoreStatus.values())
def test_arithmetic_matches_actual_pipeline_business_fit(status: str) -> None:
    candidates = _crossing_candidates()
    candidates[1][COST] = (Decimal("0.2"), status)
    result = analyze_weight_sensitivity(
        candidate_dimensions=candidates, weights=WEIGHTS, eligible_candidate_ids=[1, 2]
    )
    for row in result["scenarios_tested"]:
        actual_weights = {name: Decimal(value) for name, value in row["weights"].items()}
        for key, measurements in candidates.items():
            pipeline_dimensions = {
                name: (
                    Decimal(str(score)) if score is not None else None,
                    state,
                    "synthetic fixture",
                )
                for name, (score, state) in measurements.items()
            }
            expected = _business_fit(actual_weights, pipeline_dimensions)
            assert row["scores"][str(key)] == (str(expected) if expected is not None else None)


def test_payload_is_model_compatible_without_persistence_and_scenarios_are_json() -> None:
    result = _crossing_result()
    row = DecisionSensitivityResult(
        decision_run_id=1, analysis_code="synthetic_weight_sensitivity", **result
    )
    assert row.score_variance == Decimal("0.000252")
    assert row.sensitivity_status in SensitivityStatus.values()
    assert json.loads(json.dumps(row.scenarios_tested, allow_nan=False)) == row.scenarios_tested
    assert set(result) == {
        "ranking_stability",
        "score_variance",
        "top_candidate_change_count",
        "critical_assumption_count",
        "sensitivity_status",
        "scenarios_tested",
    }


@pytest.mark.parametrize(
    "invalid", ["NaN", "sNaN", "Infinity", "-Infinity", "-0.1", "1.01", "bad", True]
)
def test_invalid_weights_or_scores_are_rejected_not_reported_stable(invalid: NumericInput) -> None:
    with pytest.raises(ValueError, match="finite number"):
        analyze_weight_sensitivity(
            candidate_dimensions=_crossing_candidates(),
            weights={COST: invalid},
            eligible_candidate_ids=[1, 2],
        )
    candidates = _crossing_candidates()
    candidates[1][COST] = (invalid, SCORED)
    with pytest.raises(ValueError, match="finite number"):
        analyze_weight_sensitivity(
            candidate_dimensions=candidates, weights=WEIGHTS, eligible_candidate_ids=[1, 2]
        )


@pytest.mark.parametrize("invalid", [0, -1, True])
def test_invalid_baseline_ranks_are_rejected(invalid: int) -> None:
    with pytest.raises(ValueError, match="baseline ranks"):
        analyze_weight_sensitivity(
            candidate_dimensions=_crossing_candidates(),
            weights=WEIGHTS,
            eligible_candidate_ids=[1, 2],
            baseline_ranks={1: invalid, 2: 1},
        )


def test_unknown_dimensions_statuses_and_candidate_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown scoring dimensions"):
        analyze_weight_sensitivity(
            candidate_dimensions=_crossing_candidates(),
            weights={"vendor_bonus": 1},
            eligible_candidate_ids=[1, 2],
        )
    with pytest.raises(ValueError, match="unknown scoring dimension"):
        analyze_weight_sensitivity(
            candidate_dimensions={1: {"made_up": (1, SCORED)}},
            weights=WEIGHTS,
            eligible_candidate_ids=[1],
        )
    with pytest.raises(ValueError, match="unknown dimension score status"):
        analyze_weight_sensitivity(
            candidate_dimensions={1: {COST: (1, "made_up")}},
            weights=WEIGHTS,
            eligible_candidate_ids=[1],
        )
    with pytest.raises(ValueError, match="candidate IDs must be positive integers"):
        analyze_weight_sensitivity(
            candidate_dimensions={0: _measured("1", "1")},
            weights=WEIGHTS,
            eligible_candidate_ids=[],
        )
    with pytest.raises(ValueError, match="eligible candidate IDs"):
        analyze_weight_sensitivity(
            candidate_dimensions=_crossing_candidates(),
            weights=WEIGHTS,
            eligible_candidate_ids=[1, 999],
        )
    with pytest.raises(ValueError, match="baseline candidate IDs"):
        analyze_weight_sensitivity(
            candidate_dimensions=_crossing_candidates(),
            weights=WEIGHTS,
            eligible_candidate_ids=[1, 2],
            baseline_ranks={999: 1},
        )
