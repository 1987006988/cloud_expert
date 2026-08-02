from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol


class ScoreCallable(Protocol):
    def __call__(self, observed: Any, expected: Any) -> Decimal: ...


ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")


def clamp(value: Decimal) -> Decimal:
    return min(max(value, ZERO), ONE).quantize(Decimal("0.0001"))


def exact_match(observed: Any, expected: Any) -> Decimal:
    return ONE if observed == expected else ZERO


def boolean_match(observed: Any, expected: Any) -> Decimal:
    if not isinstance(observed, bool) or not isinstance(expected, bool):
        return ZERO
    return ONE if observed is expected else ZERO


def ratio_fit(observed: Any, expected: Any) -> Decimal:
    if observed is None or expected in (None, 0, "0"):
        return ZERO
    observed_decimal = Decimal(str(observed))
    expected_decimal = Decimal(str(expected))
    return clamp(observed_decimal / expected_decimal)


def threshold_fit(observed: Any, expected: Any) -> Decimal:
    if observed is None or expected is None:
        return ZERO
    return ONE if Decimal(str(observed)) >= Decimal(str(expected)) else ZERO


def range_fit(observed: Any, expected: Any) -> Decimal:
    if observed is None or not isinstance(expected, dict):
        return ZERO
    observed_decimal = Decimal(str(observed))
    minimum = expected.get("min")
    maximum = expected.get("max")
    if minimum is not None and observed_decimal < Decimal(str(minimum)):
        return ZERO
    if maximum is not None and observed_decimal > Decimal(str(maximum)):
        return ZERO
    return ONE


def categorical_fit(observed: Any, expected: Any) -> Decimal:
    if isinstance(expected, list):
        return ONE if observed in expected else ZERO
    return exact_match(observed, expected)


def completeness_fit(observed: Any, expected: Any) -> Decimal:
    threshold = Decimal(str(expected or "1"))
    value = Decimal(str(observed or "0"))
    return ONE if value >= threshold else clamp(value / threshold)


def freshness_fit(observed: Any, expected: Any) -> Decimal:
    order = {"fresh": 4, "due_soon": 3, "historical": 2, "unknown": 1, "stale": 0}
    observed_rank = order.get(str(observed), 0)
    expected_rank = order.get(str(expected), 4)
    return ONE if observed_rank >= expected_rank else clamp(Decimal(observed_rank) / Decimal(4))


def evidence_fit(observed: Any, expected: Any) -> Decimal:
    return completeness_fit(observed, expected)


REGISTRY: dict[str, ScoreCallable] = {
    "exact_match": exact_match,
    "boolean_match": boolean_match,
    "range_fit": range_fit,
    "ratio_fit": ratio_fit,
    "threshold_fit": threshold_fit,
    "categorical_fit": categorical_fit,
    "tiered_fit": categorical_fit,
    "completeness_fit": completeness_fit,
    "freshness_fit": freshness_fit,
    "evidence_fit": evidence_fit,
}


def get_score_function(name: str) -> ScoreCallable:
    if name == "custom_registered":
        raise ValueError("custom_registered score functions must be explicitly implemented first")
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"unknown score function: {name}") from exc
