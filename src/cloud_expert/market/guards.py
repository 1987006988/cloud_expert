from __future__ import annotations

from cloud_expert.database.enums import MarketMode
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.market import MarketContext
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.market.scopes import assess_compatibility, resolve_market_scope


def validate_market_context(context: MarketContext, *, purpose: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if context.market_mode not in MarketMode.values():
        reasons.append("market_mode_invalid")
    if context.market_mode == MarketMode.UNKNOWN.value:
        reasons.append("market_scope_missing")
    if context.market_mode == MarketMode.CROSS_MARKET_ANALYSIS.value and purpose != "research":
        reasons.append("cross_market_analysis_internal_only")
    if context.market_mode == MarketMode.DOMESTIC.value and context.country_code != "CN":
        reasons.append("domestic_requires_cn")
    if context.market_mode == MarketMode.INTERNATIONAL.value and not context.country_code:
        reasons.append("international_country_required")
    if purpose in {"pricing", "tco", "decision", "sales"}:
        if len(context.provider_partition_codes) != 1:
            reasons.append("single_partition_required")
        if len(context.preferred_region_codes) != 1:
            reasons.append("single_region_required")
        if not context.target_currency:
            reasons.append("currency_required")
    return tuple(reasons)


def guard_price_snapshot(context: MarketContext, snapshot: PriceSnapshot) -> tuple[str, ...]:
    reasons = list(validate_market_context(context, purpose="pricing"))
    price_scope = resolve_market_scope(snapshot)
    if price_scope.reason:
        reasons.append(price_scope.reason)
    if price_scope.partition_code is None:
        reasons.append("price_partition_missing")
    elif price_scope.partition_code not in context.provider_partition_codes:
        reasons.append("price_partition_mismatch")
    if price_scope.country_code is None:
        reasons.append("price_country_missing")
    if price_scope.region_code is None:
        reasons.append("price_region_missing")
    comparison = assess_compatibility(resolve_market_scope(context), price_scope, purpose="pricing")
    if not comparison.allowed_for_customer:
        reasons.extend(comparison.reasons)
    source_partition = snapshot.evidence.source_document.cloud_partition
    if source_partition is None:
        reasons.append("price_evidence_partition_missing")
    elif source_partition != price_scope.partition_code:
        reasons.append("price_evidence_partition_mismatch")
    return tuple(dict.fromkeys(reasons))


def guard_mapping_candidate(context: MarketContext, candidate: MappingCandidate) -> tuple[str, ...]:
    reasons = list(
        validate_market_context(
            context,
            purpose="research"
            if context.market_mode == MarketMode.CROSS_MARKET_ANALYSIS.value
            else "mapping",
        )
    )
    if candidate.rule_set.market_mode == "cross_market":
        if context.market_mode != MarketMode.CROSS_MARKET_ANALYSIS.value:
            reasons.append("cross_market_mapping_in_normal_context")
    elif candidate.rule_set.market_mode != context.market_mode:
        reasons.append("mapping_market_mismatch")
    if candidate.blocking_reasons:
        reasons.append("mapping_has_blockers")
    return tuple(dict.fromkeys(reasons))
