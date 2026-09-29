from decimal import Decimal

import pytest

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.tco import CostCalculationRun, CostLineItem, PricingScenario
from cloud_expert.pricing import tco


def _item(dimension, amount, *, currency="USD", tax="tax_excluded", warning=None):
    return CostLineItem(
        provider_id=1,
        product_id=2,
        dimension=dimension,
        amount=Decimal(amount) if amount is not None else None,
        currency=currency,
        tax_status=tax,
        warning=warning,
    )


def _aggregate(monkeypatch, items, *, declared=None, tax_scope="pre_tax", freshness="fresh"):
    monkeypatch.setattr(tco, "price_snapshot_freshness", lambda _: freshness)
    scenario = PricingScenario(
        id=1,
        target_currency="USD",
        billing_period="monthly",
        workload_profile={"required_cost_dimensions": declared or []},
        assumptions={"tax_scope": tax_scope},
    )
    return tco._results_from_line_items(CostCalculationRun(id=1), scenario, items)


def test_aggregate_all_dimensions_once_without_inventing_zero_tax(monkeypatch):
    (result,) = _aggregate(
        monkeypatch,
        [_item("compute", "10.25"), _item("disk", "2.50")],
        declared=["compute", "disk"],
    )
    assert result.subtotal == Decimal("12.75")
    assert result.total == Decimal("12.75")
    assert result.tax_amount is None
    assert result.completeness_status == "complete"


@pytest.mark.parametrize(
    "items,declared,tax_scope,status,total",
    [
        (
            [_item("compute", "10"), _item("disk", None)],
            ["compute", "disk"],
            "pre_tax",
            "missing_price",
            None,
        ),
        ([_item("compute", "10")], ["compute", "disk"], "pre_tax", "partial", Decimal("10")),
        ([_item("compute", "10")], [], "pre_tax", "partial", Decimal("10")),
        (
            [_item("compute", "10"), _item("compute", "10")],
            ["compute"],
            "pre_tax",
            "requires_review",
            None,
        ),
        ([_item("compute", "10", currency="CNY")], ["compute"], "pre_tax", "requires_review", None),
        (
            [_item("compute", "10", tax="tax_unknown")],
            ["compute"],
            "unknown",
            "partial",
            Decimal("10"),
        ),
        ([_item("compute", None)], ["compute"], "pre_tax", "missing_price", None),
        (
            [_item("compute", "10", tax="tax_unknown")],
            ["compute"],
            "pre_tax",
            "partial",
            Decimal("10"),
        ),
        (
            [_item("compute", "10", tax="tax_included")],
            ["compute"],
            "pre_tax",
            "partial",
            Decimal("10"),
        ),
        (
            [_item("compute", "10", tax="tax_included")],
            ["compute"],
            "tax_included",
            "complete",
            Decimal("10"),
        ),
    ],
)
def test_incomplete_or_conflicting_scope_cannot_be_complete(
    monkeypatch, items, declared, tax_scope, status, total
):
    (result,) = _aggregate(monkeypatch, items, declared=declared, tax_scope=tax_scope)
    assert result.completeness_status == status
    assert result.total == total
    assert result.tax_amount is None


def test_stale_price_never_produces_complete_tco(monkeypatch):
    (result,) = _aggregate(
        monkeypatch, [_item("compute", "10")], declared=["compute"], freshness="stale"
    )
    assert result.completeness_status == "partial"
    assert result.freshness_status == "stale"


def test_results_are_separate_for_different_products(monkeypatch):
    item = _item("compute", "10")
    other = _item("compute", "20")
    other.product_id = 3
    results = _aggregate(monkeypatch, [item, other], declared=["compute"])
    assert {result.product_id: result.total for result in results} == {
        2: Decimal("10"),
        3: Decimal("20"),
    }


@pytest.mark.parametrize("quantity", ["501", "-1"])
def test_usage_outside_evidenced_tier_is_not_extrapolated(quantity):
    arguments = {
        "run": CostCalculationRun(id=1),
        "provider": Provider(id=1, code="synthetic"),
        "product": Product(id=2, code="synthetic"),
        "dimension": tco.WorkloadDimension(
            "synthetic", "storage", Decimal(quantity), "GB-month", "GB-month"
        ),
        "snapshot": PriceSnapshot(
            unit_price=Decimal("1"), minimum_quantity=Decimal("0"), maximum_quantity=Decimal("500")
        ),
    }
    if quantity == "-1":
        with pytest.raises(ValueError, match="negative"):
            tco._line_item_for_dimension(**arguments)
    else:
        item = tco._line_item_for_dimension(**arguments)
        assert item.amount is None
        assert "additional tiers" in item.missing_reason
