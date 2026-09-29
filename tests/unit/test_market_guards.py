from datetime import UTC, datetime
from decimal import Decimal

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.mapping import MappingCandidate, MappingRuleSet
from cloud_expert.database.models.market import MarketContext
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.market.guards import (
    guard_mapping_candidate,
    guard_price_snapshot,
    validate_market_context,
)


def _context(
    mode: str = "international",
    country: str | None = "US",
    partition: str = "aws",
    region: str = "us-east-1",
    currency: str = "USD",
) -> MarketContext:
    return MarketContext(
        context_code="test",
        market_mode=mode,
        country_code=country,
        preferred_region_codes=[region],
        provider_partition_codes=[partition],
        target_currency=currency,
        tax_context="tax_excluded",
    )


def _price_snapshot(
    *,
    mode: str = "international",
    country: str = "US",
    partition: str = "aws",
    region_code: str = "us-east-1",
    currency: str = "USD",
    source_partition: str | None = "aws",
) -> PriceSnapshot:
    provider = Provider(code="aws", name="AWS", display_name="AWS")
    cloud_partition = CloudPartition(
        provider=provider,
        partition_code=partition,
        partition_name=partition,
        market_mode=mode,
    )
    region = Region(
        provider=provider,
        cloud_partition=cloud_partition,
        code=region_code,
        name=region_code,
        country_code=country,
        market_mode=mode,
    )
    product = Product(
        provider=provider, market_mode=mode, code="s3", official_name="S3", display_name="S3"
    )
    price_sku = PriceSKU(
        provider=provider, product=product, region=region, currency=currency, tax_included=False
    )
    source = SourceDocument(provider=provider, cloud_partition=source_partition)
    evidence = Evidence(source_document=source)
    return PriceSnapshot(
        price_sku=price_sku,
        evidence=evidence,
        unit_price=Decimal("0.01"),
        captured_at=datetime.now(UTC),
    )


def test_price_guard_requires_exact_market_region_currency_and_source_partition() -> None:
    context = _context()
    assert guard_price_snapshot(context, _price_snapshot()) == ()
    assert "different_region" in guard_price_snapshot(
        context, _price_snapshot(region_code="us-west-2")
    )
    assert "price_partition_mismatch" in guard_price_snapshot(
        context, _price_snapshot(partition="aws_china")
    )
    assert "currency_mismatch" in guard_price_snapshot(context, _price_snapshot(currency="CNY"))
    assert "price_evidence_partition_mismatch" in guard_price_snapshot(
        context, _price_snapshot(source_partition="aws_china")
    )


def test_international_without_country_and_cross_market_mapping_are_blocked() -> None:
    assert "international_country_required" in validate_market_context(
        _context(country=None), purpose="decision"
    )
    rule_set = MappingRuleSet(market_mode="cross_market")
    candidate = MappingCandidate(rule_set=rule_set, blocking_reasons=[])
    assert "cross_market_mapping_in_normal_context" in guard_mapping_candidate(
        _context(), candidate
    )
    research = _context(mode="cross_market_analysis")
    assert guard_mapping_candidate(research, candidate) == ()
