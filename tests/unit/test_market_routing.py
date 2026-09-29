from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.mapping import MappingCandidate, MappingRuleSet
from cloud_expert.database.models.market import MarketContext
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.market import routing
from cloud_expert.market.routing import (
    filter_mapping_candidates,
    route_regions,
    select_price_snapshot,
)
from tests.unit.test_market_guards import _context, _price_snapshot


def _region(provider: Provider, code: str, country: str, partition: str) -> Region:
    return Region(
        provider=provider,
        cloud_partition=CloudPartition(
            provider=provider,
            partition_code=partition,
            partition_name=partition,
            market_mode="international",
        ),
        code=code,
        name=code,
        country_code=country,
        market_mode="international",
        is_active=True,
    )


def test_mexico_has_no_implicit_us_region_fallback() -> None:
    provider = Provider(code="aws", name="AWS", display_name="AWS")
    context = MarketContext(
        context_code="mx",
        market_mode="international",
        country_code="MX",
        preferred_region_codes=[],
        provider_partition_codes=["aws"],
        tax_context="tax_unknown",
    )
    result = route_regions(context, [_region(provider, "us-east-1", "US", "aws")])
    assert result.status == "no_local_region"
    assert result.regions == ()


def test_international_without_country_needs_context() -> None:
    context = MarketContext(
        context_code="overseas",
        market_mode="international",
        country_code=None,
        preferred_region_codes=[],
        provider_partition_codes=[],
        tax_context="tax_unknown",
    )
    assert route_regions(context, []).status == "insufficient_market_context"


def test_price_selection_rejects_wrong_region_and_currency(monkeypatch, session: Session) -> None:
    context = _context()
    wrong = _price_snapshot(region_code="us-west-2")
    assert select_price_snapshot(context, [wrong]).status == "market_scope_mismatch"
    assert select_price_snapshot(context, []).status == "missing_price"
    right = _price_snapshot()
    assert select_price_snapshot(context, [right]).status == "price_not_current"
    monkeypatch.setattr(routing, "aws_price_current", lambda *_: True)
    assert select_price_snapshot(context, [wrong, right], session=session).snapshot is right


def test_revoked_aws_price_is_not_routed(monkeypatch, session: Session) -> None:
    monkeypatch.setattr(routing, "aws_price_current", lambda *_: False)
    result = select_price_snapshot(_context(), [_price_snapshot()], session=session)
    assert result.snapshot is None
    assert result.reasons == ("price_policy_not_verified",)


def test_price_selection_fails_closed_for_stale_and_unknown_snapshots() -> None:
    context = _context()
    stale = _price_snapshot()
    stale.captured_at = datetime.now(UTC) - timedelta(days=20)
    assert select_price_snapshot(context, [stale]).status == "price_not_current"
    unknown = _price_snapshot()
    unknown.captured_at = None
    assert select_price_snapshot(context, [unknown]).status == "price_not_current"


def test_rejected_and_superseded_mappings_are_not_routed() -> None:
    context = _context(mode="domestic", country="CN", partition="huawei_cn")
    rule = MappingRuleSet(market_mode="domestic")
    candidates = [
        MappingCandidate(rule_set=rule, candidate_status=status, blocking_reasons=[])
        for status in ("candidate", "rejected", "superseded")
    ]
    assert filter_mapping_candidates(context, candidates) == (candidates[0],)
