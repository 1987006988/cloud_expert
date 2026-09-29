from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.market import MarketContext
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.region import Region
from cloud_expert.market.guards import (
    guard_mapping_candidate,
    guard_price_snapshot,
    validate_market_context,
)
from cloud_expert.pricing.consumption import aws_price_current, is_aws_price
from cloud_expert.pricing.freshness import price_snapshot_freshness


@dataclass(frozen=True)
class RegionRoutingResult:
    status: str
    regions: tuple[Region, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PriceSelectionResult:
    status: str
    snapshot: PriceSnapshot | None
    reasons: tuple[str, ...]


def route_regions(context: MarketContext, regions: Iterable[Region]) -> RegionRoutingResult:
    reasons = validate_market_context(context, purpose="mapping")
    if reasons:
        return RegionRoutingResult("insufficient_market_context", (), reasons)
    if not context.country_code:
        return RegionRoutingResult("insufficient_market_context", (), ("country_scope_missing",))
    matched = tuple(
        region
        for region in regions
        if region.is_active
        and region.market_mode == context.market_mode
        and region.country_code == context.country_code
        and region.cloud_partition is not None
        and region.cloud_partition.partition_code in context.provider_partition_codes
        and (not context.preferred_region_codes or region.code in context.preferred_region_codes)
    )
    if matched:
        return RegionRoutingResult("local_region_candidates", matched, ())
    return RegionRoutingResult("no_local_region", (), ("no_proven_region_in_country",))


def filter_products(context: MarketContext, products: Iterable[Product]) -> tuple[Product, ...]:
    return tuple(product for product in products if product.market_mode == context.market_mode)


def filter_mapping_candidates(
    context: MarketContext, candidates: Iterable[MappingCandidate]
) -> tuple[MappingCandidate, ...]:
    return tuple(
        candidate
        for candidate in candidates
        if candidate.candidate_status not in {"rejected", "superseded"}
        and not guard_mapping_candidate(context, candidate)
    )


def select_price_snapshot(
    context: MarketContext, snapshots: Iterable[PriceSnapshot], *, session: Session | None = None
) -> PriceSelectionResult:
    valid: list[PriceSnapshot] = []
    rejected_reasons: set[str] = set()
    freshness_reasons: set[str] = set()
    for snapshot in snapshots:
        reasons = guard_price_snapshot(context, snapshot)
        if reasons:
            rejected_reasons.update(reasons)
        elif (freshness := price_snapshot_freshness(snapshot)) != "fresh":
            freshness_reasons.add(f"price_{freshness}")
        elif is_aws_price(snapshot) and (
            session is None or not aws_price_current(session, snapshot)
        ):
            freshness_reasons.add("price_policy_not_verified")
        else:
            valid.append(snapshot)
    if valid:
        latest = max(valid, key=lambda item: (_timestamp(item.captured_at), item.id or 0))
        return PriceSelectionResult("selected", latest, ())
    if freshness_reasons:
        return PriceSelectionResult("price_not_current", None, tuple(sorted(freshness_reasons)))
    if rejected_reasons:
        return PriceSelectionResult("market_scope_mismatch", None, tuple(sorted(rejected_reasons)))
    return PriceSelectionResult("missing_price", None, ("no_price_snapshot",))


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()
