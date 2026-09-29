from cloud_expert.database.enums import MarketMode
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.market import MarketContext
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.market.scopes import MarketScope, assess_compatibility, resolve_market_scope


def _scope(
    mode: str,
    *,
    provider: str = "aws",
    partition: str = "aws",
    country: str = "US",
    region: str = "us-east-1",
) -> MarketScope:
    return MarketScope(
        market_mode=mode,
        provider_code=provider,
        partition_code=partition,
        country_code=country,
        region_code=region,
        currency="USD",
        tax_context="tax_excluded",
    )


def test_market_modes_include_unknown_and_research_without_expanding_fact_values() -> None:
    assert set(MarketMode.values()) == {
        "domestic",
        "international",
        "cross_market_analysis",
        "unknown",
    }
    assert MarketMode.fact_values() == ("domestic", "international")


def test_price_scope_blocks_different_partition_region_currency_and_tax() -> None:
    commercial = _scope("international")
    assert (
        assess_compatibility(
            commercial, _scope("international", partition="aws_china"), purpose="pricing"
        ).status
        == "incompatible"
    )
    assert assess_compatibility(
        commercial, _scope("international", region="us-west-2"), purpose="pricing"
    ).reasons == ("different_region",)
    assert assess_compatibility(
        commercial, MarketScope(**{**commercial.__dict__, "currency": "EUR"}), purpose="tco"
    ).reasons == ("currency_mismatch",)
    assert assess_compatibility(
        commercial,
        MarketScope(**{**commercial.__dict__, "tax_context": "tax_included"}),
        purpose="tco",
    ).reasons == ("tax_context_mismatch",)


def test_cross_market_and_missing_country_never_pass_customer_guard() -> None:
    domestic = _scope(
        "domestic",
        provider="huawei_cloud",
        partition="huawei_cn",
        country="CN",
        region="cn-north-4",
    )
    international = _scope("international")
    assert (
        assess_compatibility(domestic, international, purpose="research").status == "cross_market"
    )
    assert not assess_compatibility(
        domestic, international, purpose="research"
    ).allowed_for_customer
    assert (
        assess_compatibility(
            _scope("international", country=""), international, purpose="decision"
        ).status
        == "unknown"
    )
    assert (
        assess_compatibility(_scope("unknown"), international, purpose="sales").status == "unknown"
    )


def test_different_providers_can_map_within_same_country() -> None:
    huawei = _scope(
        "domestic",
        provider="huawei_cloud",
        partition="huawei_cn",
        country="CN",
        region="cn-north-4",
    )
    aliyun = _scope(
        "domestic",
        provider="aliyun",
        partition="aliyun_public_cn",
        country="CN",
        region="cn-beijing",
    )
    assert assess_compatibility(huawei, aliyun, purpose="mapping").status == "compatible"
    assert assess_compatibility(huawei, aliyun, purpose="pricing").status == "incompatible"


def test_resolver_does_not_guess_country_or_partition() -> None:
    provider = Provider(code="aws", name="AWS")
    partition = CloudPartition(
        provider=provider,
        partition_code="aws",
        partition_name="AWS Commercial",
        market_mode="international",
    )
    region = Region(
        provider=provider,
        cloud_partition=partition,
        code="us-east-1",
        name="US East",
        country_code="US",
        market_mode="international",
    )
    scope = resolve_market_scope(region)
    assert (scope.partition_code, scope.country_code, scope.region_code) == (
        "aws",
        "US",
        "us-east-1",
    )
    context = MarketContext(
        context_code="unknown-example",
        market_mode="international",
        country_code=None,
        preferred_region_codes=[],
        provider_partition_codes=[],
        tax_context="tax_unknown",
    )
    assert resolve_market_scope(context).country_code is None
    assert (
        assess_compatibility(resolve_market_scope(context), scope, purpose="decision").status
        == "unknown"
    )
