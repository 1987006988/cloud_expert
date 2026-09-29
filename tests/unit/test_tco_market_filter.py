from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from cloud_expert.pricing.tco import _latest_snapshot_for_dimension
from tests.fixtures.synthetic_data import load_synthetic_fixture


@pytest.mark.parametrize("approved", [True, False])
def test_aws_selector_rechecks_current_policy_before_consumption(session, monkeypatch, approved):
    from cloud_expert.pricing import consumption

    fixture = load_synthetic_fixture(session)
    fixture["provider"].code = "aws"
    fixture["snapshot"].evidence.parser_rule = consumption.AWS_CATALOG_RULE
    session.flush()
    observed = []

    def validate(current_session, price, *, raw_root):
        observed.append((current_session, price, raw_root))
        return approved

    monkeypatch.setattr(consumption, "aws_catalog_price_valid", validate)
    result = _latest_snapshot_for_dimension(
        session,
        provider_id=fixture["provider"].id,
        product_id=fixture["product"].id,
        billing_unit="synthetic-hour",
        market_mode="domestic",
        currency="USD",
        region_code=fixture["region"].code,
        provider_price_code=fixture["price_sku"].provider_price_code,
    )
    assert result == (fixture["snapshot"] if approved else None)
    assert len(observed) == 1
    assert observed[0][1] == fixture["snapshot"]


def test_legacy_tco_does_not_select_price_from_other_market_or_currency(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    provider = fixture["provider"]
    product = fixture["product"]
    selected = _latest_snapshot_for_dimension(
        session,
        provider_id=provider.id,
        product_id=product.id,
        billing_unit="synthetic-hour",
        market_mode="domestic",
        currency="USD",
        region_code=fixture["region"].code,
        provider_price_code=fixture["price_sku"].provider_price_code,
    )
    assert selected is not None
    assert (
        _latest_snapshot_for_dimension(
            session,
            provider_id=provider.id,
            product_id=product.id,
            billing_unit="synthetic-hour",
            market_mode="international",
            currency="USD",
            region_code=fixture["region"].code,
            provider_price_code=fixture["price_sku"].provider_price_code,
        )
        is None
    )
    assert (
        _latest_snapshot_for_dimension(
            session,
            provider_id=provider.id,
            product_id=product.id,
            billing_unit="synthetic-hour",
            market_mode="domestic",
            currency="EUR",
            region_code=fixture["region"].code,
            provider_price_code=fixture["price_sku"].provider_price_code,
        )
        is None
    )


def test_legacy_tco_requires_exact_region_and_price_identity(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    kwargs = {
        "provider_id": fixture["provider"].id,
        "product_id": fixture["product"].id,
        "billing_unit": "synthetic-hour",
        "market_mode": "domestic",
        "currency": "USD",
    }
    assert _latest_snapshot_for_dimension(session, **kwargs) is None
    assert (
        _latest_snapshot_for_dimension(session, **kwargs, region_code=fixture["region"].code)
        is None
    )
    assert (
        _latest_snapshot_for_dimension(
            session,
            **kwargs,
            region_code="synthetic-other-region",
            provider_price_code=fixture["price_sku"].provider_price_code,
        )
        is None
    )


def test_legacy_flat_rate_selector_does_not_pick_a_graduated_tier(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    fixture["snapshot"].maximum_quantity = Decimal("100")
    session.flush()
    assert (
        _latest_snapshot_for_dimension(
            session,
            provider_id=fixture["provider"].id,
            product_id=fixture["product"].id,
            billing_unit="synthetic-hour",
            market_mode="domestic",
            currency="USD",
            region_code=fixture["region"].code,
            provider_price_code=fixture["price_sku"].provider_price_code,
        )
        is None
    )
