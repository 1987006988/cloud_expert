from decimal import Decimal

from cloud_expert.database.enums import (
    ComparabilityStatus,
    ReviewStatus,
    SpecificationScopeType,
    ValueQualifier,
)
from cloud_expert.normalization.canonical_service import (
    FieldReadiness,
    _comparability_decision,
)


def _readiness(
    *,
    count: int = 1,
    scope: str = SpecificationScopeType.SKU.value,
    unit: str = "count",
    qualifier: str = ValueQualifier.EXACT.value,
    pending: int = 0,
) -> FieldReadiness:
    return FieldReadiness(
        count=count,
        scope_types=frozenset({scope}) if count else frozenset(),
        canonical_units=frozenset({unit}) if count and unit else frozenset(),
        value_qualifiers=frozenset({qualifier}) if count else frozenset(),
        pending_review_count=pending,
    )


def test_comparability_decision_blocks_missing_values() -> None:
    missing = _readiness(count=0, unit="")
    ready = _readiness()

    both_missing = _comparability_decision(
        missing,
        missing,
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="domestic",
    )
    assert both_missing.status == ComparabilityStatus.NOT_COMPARABLE.value
    assert both_missing.reason_code == "missing_both_sides"
    assert both_missing.overall_score == Decimal("0.0000")

    one_missing = _comparability_decision(
        ready,
        missing,
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="domestic",
    )
    assert one_missing.status == ComparabilityStatus.PARTIAL.value
    assert one_missing.reason_code == "missing_one_side"


def test_comparability_decision_routes_blockers_to_review() -> None:
    pending = _comparability_decision(
        _readiness(pending=1),
        _readiness(),
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="domestic",
    )
    assert pending.status == ComparabilityStatus.NEEDS_REVIEW.value
    assert pending.reason_code == "pending_review_values"

    scope = _comparability_decision(
        _readiness(scope=SpecificationScopeType.PRODUCT.value),
        _readiness(),
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="domestic",
    )
    assert scope.reason_code == "scope_mismatch"
    assert scope.scope_compatibility_score == Decimal("0.2500")

    unit = _comparability_decision(
        _readiness(unit="GiB"),
        _readiness(unit="GB"),
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="domestic",
    )
    assert unit.reason_code == "unit_mismatch"
    assert unit.unit_compatibility_score == Decimal("0.2500")

    qualifier = _comparability_decision(
        _readiness(qualifier=ValueQualifier.BASELINE.value),
        _readiness(qualifier=ValueQualifier.MAXIMUM.value),
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="domestic",
    )
    assert qualifier.reason_code == "qualifier_mismatch"


def test_comparability_decision_handles_market_scope_and_success() -> None:
    market = _comparability_decision(
        _readiness(),
        _readiness(),
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="international",
    )
    assert market.status == ComparabilityStatus.PARTIAL.value
    assert market.reason_code == "market_scope_differs"

    comparable = _comparability_decision(
        _readiness(),
        _readiness(),
        expected_scope_type=SpecificationScopeType.SKU.value,
        source_market_mode="domestic",
        target_market_mode="domestic",
    )
    assert comparable.status == ComparabilityStatus.COMPARABLE.value
    assert comparable.review_status == ReviewStatus.MACHINE_EXTRACTED.value
