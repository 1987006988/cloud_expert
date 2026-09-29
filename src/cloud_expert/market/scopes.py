from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from cloud_expert.database.enums import MarketCompatibilityStatus, MarketMode
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionScenario
from cloud_expert.database.models.market import MarketContext
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.region import Availability, Region
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.tco import PricingScenario, TCOResult

RULE_VERSION = "week12_market_scope_v1"


@dataclass(frozen=True)
class MarketScope:
    market_mode: str = MarketMode.UNKNOWN.value
    provider_code: str | None = None
    partition_code: str | None = None
    country_code: str | None = None
    region_code: str | None = None
    currency: str | None = None
    tax_context: str | None = None
    reason: str | None = None

    def fingerprint(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScopeAssessment:
    status: str
    reasons: tuple[str, ...]
    left: MarketScope
    right: MarketScope

    @property
    def allowed_for_customer(self) -> bool:
        return self.status == MarketCompatibilityStatus.COMPATIBLE.value


def resolve_market_scope(entity: object) -> MarketScope:
    if isinstance(entity, MarketContext):
        return MarketScope(
            market_mode=entity.market_mode,
            partition_code=_single(entity.provider_partition_codes),
            country_code=entity.country_code,
            region_code=_single(entity.preferred_region_codes),
            currency=entity.target_currency,
            tax_context=entity.tax_context,
        )
    if isinstance(entity, CloudPartition):
        return MarketScope(
            market_mode=entity.market_mode,
            provider_code=entity.provider.code,
            partition_code=entity.partition_code,
        )
    if isinstance(entity, Region):
        return MarketScope(
            market_mode=entity.market_mode,
            provider_code=entity.provider.code,
            partition_code=(
                entity.cloud_partition.partition_code if entity.cloud_partition else None
            ),
            country_code=entity.country_code if entity.country_code != "ZZ" else None,
            region_code=entity.code,
            reason="country_unresolved" if entity.country_code == "ZZ" else None,
        )
    if isinstance(entity, Availability):
        return resolve_market_scope(entity.region)
    if isinstance(entity, Product):
        return MarketScope(market_mode=entity.market_mode, provider_code=entity.provider.code)
    if isinstance(entity, SKU):
        return resolve_market_scope(entity.product)
    if isinstance(entity, SourceDocument):
        return MarketScope(
            provider_code=entity.provider.code,
            partition_code=entity.cloud_partition,
            reason="source_market_not_explicit",
        )
    if isinstance(entity, Evidence):
        return resolve_market_scope(entity.source_document)
    if isinstance(entity, PriceSKU):
        region_scope = resolve_market_scope(entity.region)
        if entity.product.market_mode != region_scope.market_mode:
            return MarketScope(reason="price_product_region_market_mismatch")
        return MarketScope(
            market_mode=region_scope.market_mode,
            provider_code=region_scope.provider_code,
            partition_code=region_scope.partition_code,
            country_code=region_scope.country_code,
            region_code=region_scope.region_code,
            currency=entity.currency,
            tax_context="tax_included" if entity.tax_included else "tax_excluded",
        )
    if isinstance(entity, PriceSnapshot):
        return resolve_market_scope(entity.price_sku)
    if isinstance(entity, PricingScenario):
        return MarketScope(
            market_mode=entity.market_mode,
            currency=entity.target_currency,
            reason="scenario_country_region_not_recorded",
        )
    if isinstance(entity, TCOResult):
        return resolve_market_scope(entity.scenario)
    if isinstance(entity, DecisionScenario):
        return MarketScope(
            market_mode=entity.market_mode,
            country_code=entity.country_code,
            region_code=_single(entity.preferred_regions),
        )
    if isinstance(entity, CandidateDecisionResult):
        return resolve_market_scope(entity.decision_run.scenario)
    return MarketScope(reason=f"scope_resolver_unsupported:{type(entity).__name__}")


def assess_compatibility(
    left: MarketScope, right: MarketScope, *, purpose: str = "mapping"
) -> ScopeAssessment:
    reasons: list[str] = []
    if purpose not in {"mapping", "pricing", "tco", "decision", "sales", "research"}:
        raise ValueError(f"unsupported market compatibility purpose: {purpose}")
    if (
        left.market_mode == MarketMode.UNKNOWN.value
        or right.market_mode == MarketMode.UNKNOWN.value
    ):
        return ScopeAssessment("unknown", ("market_scope_missing",), left, right)
    if MarketMode.CROSS_MARKET_ANALYSIS.value in {left.market_mode, right.market_mode}:
        return ScopeAssessment(
            "cross_market", ("cross_market_analysis_internal_only",), left, right
        )
    if left.market_mode != right.market_mode:
        return ScopeAssessment("cross_market", ("domestic_vs_international",), left, right)
    if left.market_mode == MarketMode.DOMESTIC.value and (
        left.country_code not in {None, "CN"} or right.country_code not in {None, "CN"}
    ):
        return ScopeAssessment("incompatible", ("domestic_country_mismatch",), left, right)
    if (
        left.provider_code
        and left.provider_code == right.provider_code
        and left.partition_code
        and right.partition_code
        and left.partition_code != right.partition_code
    ):
        return ScopeAssessment("incompatible", ("different_partition",), left, right)
    if left.country_code and right.country_code and left.country_code != right.country_code:
        return ScopeAssessment("incompatible", ("different_country",), left, right)
    if purpose in {"pricing", "tco", "decision", "sales"}:
        if not left.country_code or not right.country_code:
            reasons.append("country_scope_missing")
        if not left.partition_code or not right.partition_code:
            reasons.append("partition_scope_missing")
        if not left.region_code or not right.region_code:
            reasons.append("region_scope_missing")
        if left.region_code and right.region_code and left.region_code != right.region_code:
            return ScopeAssessment("incompatible", ("different_region",), left, right)
        if left.currency and right.currency and left.currency != right.currency:
            return ScopeAssessment("incompatible", ("currency_mismatch",), left, right)
        if purpose in {"tco", "sales"}:
            if not left.tax_context or not right.tax_context:
                reasons.append("tax_scope_missing")
            elif left.tax_context != right.tax_context:
                return ScopeAssessment("incompatible", ("tax_context_mismatch",), left, right)
    elif purpose == "mapping" and not left.country_code and not right.country_code:
        reasons.append("country_scope_missing")
    if reasons:
        return ScopeAssessment("unknown", tuple(reasons), left, right)
    if left.country_code is None or right.country_code is None:
        return ScopeAssessment(
            "compatible_with_conditions", ("country_scope_partial",), left, right
        )
    return ScopeAssessment("compatible", (), left, right)


def _single(values: list[str] | None) -> str | None:
    return values[0] if values and len(values) == 1 else None
