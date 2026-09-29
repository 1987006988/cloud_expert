"""Pure, measured one-at-a-time Decision weight sensitivity; no persistence."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Any, TypedDict

from cloud_expert.database.enums import DimensionScoreStatus, ScoringDimension, SensitivityStatus

type NumericInput = Decimal | int | float | str
type DimensionInputs = Mapping[int, Mapping[str, tuple[NumericInput | None, str]]]
type MeasuredDimensions = dict[int, dict[str, tuple[Decimal | None, str]]]

_SCORE_QUANTUM = Decimal("0.0001")
_VARIANCE_QUANTUM = Decimal("0.000001")
_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_OMITTED_STATUSES = {
    DimensionScoreStatus.EXCLUDED.value,
    DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
}


class SensitivityPayload(TypedDict):
    """Fields accepted by DecisionSensitivityResult, excluding run identity."""

    ranking_stability: str
    score_variance: Decimal
    top_candidate_change_count: int
    critical_assumption_count: int
    sensitivity_status: str
    scenarios_tested: list[dict[str, Any]]


def _unit_decimal(value: NumericInput, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a finite number in [0, 1]") from exc
    if not number.is_finite() or not Decimal(0) <= number <= Decimal(1):
        raise ValueError(f"{label} must be a finite number in [0, 1]")
    return number


def _scores(
    dimensions: MeasuredDimensions, weights: Mapping[str, Decimal]
) -> dict[int, Decimal | None]:
    scores: dict[int, Decimal | None] = {}
    for candidate_id, measurements in dimensions.items():
        numerator = Decimal(0)
        denominator = Decimal(0)
        for dimension, (score, status) in measurements.items():
            if score is None or status in _OMITTED_STATUSES:
                continue
            weight = weights.get(dimension, Decimal(0))
            numerator += score * weight
            denominator += weight
        scores[candidate_id] = (
            (numerator / denominator).quantize(_SCORE_QUANTUM) if denominator else None
        )
    return scores


def _ranking(
    scores: Mapping[int, Decimal | None], eligible_ids: Collection[int]
) -> tuple[dict[int, int | None], list[list[int]]]:
    groups: dict[Decimal, list[int]] = {}
    for candidate_id in sorted(eligible_ids):
        score = scores[candidate_id]
        if score is not None:
            groups.setdefault(score, []).append(candidate_id)
    tie_sets = [groups[score] for score in sorted(groups, reverse=True)]
    ranks: dict[int, int | None] = dict.fromkeys(scores)
    for rank, group in enumerate(tie_sets, start=1):
        for candidate_id in group:
            ranks[candidate_id] = rank
    return ranks, tie_sets


def _snapshot(
    weights: Mapping[str, Decimal],
    scores: Mapping[int, Decimal | None],
    ranks: Mapping[int, int | None],
    tie_sets: list[list[int]],
) -> dict[str, Any]:
    return {
        "weights": {name: str(weight) for name, weight in weights.items()},
        "scores": {
            str(key): str(score) if score is not None else None for key, score in scores.items()
        },
        "ranks": {str(key): rank for key, rank in ranks.items()},
        "tie_sets": tie_sets,
        "top_candidate_ids": tie_sets[0][:] if tie_sets else [],
    }


def analyze_weight_sensitivity(
    *,
    candidate_dimensions: DimensionInputs,
    weights: Mapping[str, NumericInput],
    eligible_candidate_ids: Collection[int],
    baseline_ranks: Mapping[int, int | None] | None = None,
) -> SensitivityPayload:
    """Recompute the baseline and each positive policy weight times 0.9 and 1.1.

    Eligibility is *formal ranking* eligibility, not customer approval. The caller
    must apply the pipeline's status, hard-block, non-null business-fit and
    confidence >= 0.6500 guards. Ineligible candidates retain measured reference
    scores in the audit but cannot rank or affect summary metrics.

    Arithmetic matches pipeline._business_fit: omit null, excluded and
    insufficient-evidence dimensions; normalize by each candidate's remaining
    weight sum; round half-even to four places before dense ranking. A blocked
    positive-weight dimension on an eligible candidate makes the conclusion
    indeterminate, even though its reference arithmetic is retained. Missing
    dimensions are never imputed. Stability covers only these measured inputs.

    Optional baseline ranks are checked against recomputed ranks, never trusted
    as evidence of stability. Missing eligible ranks or mismatches make the
    conclusion indeterminate. The audit always uses the recomputed baseline.

    scenarios_tested contains one baseline followed by two scenarios per
    positive weight (dimension-name order, decrease before increase). Scores
    and weights are JSON decimal strings; unknown scores/ranks remain null.
    score_variance is the mean per-candidate population variance over baseline
    and perturbations, using scorable eligible candidates only, at Numeric(8,6)
    precision. If none are scorable the schema-required zero is explicitly
    marked unavailable in the baseline audit, not presented as measured zero.

    A changed top tie set is highly_sensitive; only lower-ranking changes are
    moderately_sensitive. critical_assumption_count counts distinct perturbed
    dimensions that change any rank, not the number of scenarios. Fewer than
    two eligible candidates, any unscorable eligible candidate, no positive
    weights, blocked dimensions or inconsistent baseline ranks are indeterminate.
    Malformed numeric inputs, unknown dimensions/statuses or IDs raise ValueError.
    Inputs are only read; this function performs no I/O or approval changes.
    """
    valid_dimensions = set(ScoringDimension.values())
    if set(weights) - valid_dimensions:
        raise ValueError("weights contain unknown scoring dimensions")
    policy_weights = {
        name: _unit_decimal(value, f"weight {name}") for name, value in sorted(weights.items())
    }
    if any(type(key) is not int or key <= 0 for key in candidate_dimensions):
        raise ValueError("candidate IDs must be positive integers")
    if any(
        type(key) is not int or key not in candidate_dimensions for key in eligible_candidate_ids
    ):
        raise ValueError("eligible candidate IDs must exist in candidate_dimensions")
    eligible_ids = sorted(set(eligible_candidate_ids))
    dimensions: MeasuredDimensions = {}
    for candidate_id, measurements in sorted(candidate_dimensions.items()):
        dimensions[candidate_id] = {}
        for name, (score, status) in sorted(measurements.items()):
            if name not in valid_dimensions:
                raise ValueError(f"unknown scoring dimension: {name}")
            if status not in DimensionScoreStatus.values():
                raise ValueError(f"unknown dimension score status: {status}")
            dimensions[candidate_id][name] = (
                _unit_decimal(score, f"score {candidate_id}/{name}") if score is not None else None,
                status,
            )
    if baseline_ranks is not None:
        for candidate_id, rank in baseline_ranks.items():
            if type(candidate_id) is not int or candidate_id not in dimensions:
                raise ValueError("baseline candidate IDs must exist in candidate_dimensions")
            if rank is not None and (type(rank) is not int or rank < 1):
                raise ValueError("baseline ranks must be positive integers or null")

    # A fixed local context keeps calculations independent of caller Decimal settings.
    with localcontext(_CONTEXT):
        return _analyze(dimensions, policy_weights, eligible_ids, baseline_ranks)


def _analyze(
    dimensions: MeasuredDimensions,
    weights: dict[str, Decimal],
    eligible_ids: list[int],
    baseline_ranks: Mapping[int, int | None] | None,
) -> SensitivityPayload:
    positive_dimensions = [name for name, weight in weights.items() if weight > 0]
    baseline_scores = _scores(dimensions, weights)
    ranks, tie_sets = _ranking(baseline_scores, eligible_ids)
    reasons: list[str] = []
    if len(eligible_ids) < 2:
        reasons.append("fewer_than_two_eligible_candidates")
    if not positive_dimensions:
        reasons.append("no_positive_weights")
    unscorable = [key for key in eligible_ids if baseline_scores[key] is None]
    if unscorable:
        reasons.append("eligible_candidates_without_valid_weighted_dimensions")
    blocked = [
        {"candidate_id": key, "dimension": name}
        for key in eligible_ids
        for name in positive_dimensions
        if name in dimensions[key]
        and dimensions[key][name][1] == DimensionScoreStatus.BLOCKED.value
    ]
    if blocked:
        reasons.append("blocked_dimensions_on_eligible_candidates")
    if baseline_ranks is not None and (
        any(key not in baseline_ranks for key in eligible_ids)
        or any(rank != ranks[key] for key, rank in baseline_ranks.items())
    ):
        reasons.append("baseline_rank_mismatch")

    history = {key: [score] for key in eligible_ids if (score := baseline_scores[key]) is not None}
    baseline = {
        "type": "baseline",
        **_snapshot(weights, baseline_scores, ranks, tie_sets),
        "eligible_candidate_ids": eligible_ids[:],
        "unscorable_candidate_ids": unscorable,
        "blocked_dimensions": blocked,
        "indeterminate_reasons": reasons,
        "supplied_baseline_ranks": (
            {str(key): rank for key, rank in sorted(baseline_ranks.items())}
            if baseline_ranks is not None
            else None
        ),
        "candidate_dimensions": {
            str(key): {
                name: {"score": str(score) if score is not None else None, "status": status}
                for name, (score, status) in measurements.items()
            }
            for key, measurements in dimensions.items()
        },
        "score_variance_available": bool(history),
        "variance_candidate_count": len(history),
        "variance_population": "baseline_and_perturbations",
    }
    scenarios = [baseline]
    top_changes = 0
    critical_dimensions: set[str] = set()
    for name in positive_dimensions:
        for multiplier in (Decimal("0.9"), Decimal("1.1")):
            perturbed = {**weights, name: weights[name] * multiplier}
            scores = _scores(dimensions, perturbed)
            scenario_ranks, scenario_ties = _ranking(scores, eligible_ids)
            ranking_changed = scenario_ties != tie_sets if not reasons else None
            top_changed = scenario_ties[:1] != tie_sets[:1] if not reasons else None
            if ranking_changed:
                critical_dimensions.add(name)
            if top_changed:
                top_changes += 1
            for key, values in history.items():
                score = scores[key]
                assert score is not None  # Positive multipliers preserve nonzero denominators.
                values.append(score)
            scenarios.append(
                {
                    "type": "weight_sensitivity",
                    "dimension": name,
                    "multiplier": str(multiplier),
                    **_snapshot(perturbed, scores, scenario_ranks, scenario_ties),
                    "ranking_changed": ranking_changed,
                    "top_candidate_changed": top_changed,
                }
            )

    variances: list[Decimal] = []
    for values in history.values():
        mean = sum(values, Decimal(0)) / len(values)
        variances.append(sum(((value - mean) ** 2 for value in values), Decimal(0)) / len(values))
    variance = sum(variances, Decimal(0)) / len(variances) if variances else Decimal(0)
    if reasons:
        status = SensitivityStatus.INDETERMINATE
        stability = "indeterminate"
    elif top_changes:
        status = SensitivityStatus.HIGHLY_SENSITIVE
        stability = "ranking_changed"
    elif critical_dimensions:
        status = SensitivityStatus.MODERATELY_SENSITIVE
        stability = "ranking_changed"
    else:
        status = SensitivityStatus.STABLE
        stability = "ranking_unchanged"
    return SensitivityPayload(
        ranking_stability=stability,
        score_variance=variance.quantize(_VARIANCE_QUANTUM),
        top_candidate_change_count=top_changes,
        critical_assumption_count=len(critical_dimensions),
        sensitivity_status=status.value,
        scenarios_tested=scenarios,
    )
