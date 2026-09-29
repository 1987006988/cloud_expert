from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    ComparabilityStatus,
    CostCalculationRunStatus,
    FreshnessStatus,
    MarketMode,
    PricingScenarioStatus,
    TaxStatus,
    TCOCompletenessStatus,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.tco import (
    CostCalculationRun,
    CostLineItem,
    PricingScenario,
    TCOResult,
)
from cloud_expert.pricing.freshness import price_snapshot_freshness

RULE_VERSION = "week14_tco_exact_price_selection_v6"
SCENARIO_CODE = "internal_price_readiness_storage_1tb_month"
SCENARIO_VERSION = "2026-07-23"
RUN_CODE = "internal_price_readiness_v2"


@dataclass(frozen=True)
class WorkloadDimension:
    product_code: str
    dimension: str
    usage_quantity: Decimal
    usage_unit: str
    billing_unit: str


WORKLOAD_DIMENSIONS = (
    WorkloadDimension(
        product_code="obs",
        dimension="standard_storage_gb_month",
        usage_quantity=Decimal("1024"),
        usage_unit="GB-month",
        billing_unit="GB-month",
    ),
    WorkloadDimension(
        product_code="s3",
        dimension="standard_storage_gb_month",
        usage_quantity=Decimal("1024"),
        usage_unit="GB-month",
        billing_unit="GB-month",
    ),
    WorkloadDimension(
        product_code="oss",
        dimension="standard_storage_gb_month",
        usage_quantity=Decimal("1024"),
        usage_unit="GB-month",
        billing_unit="GB-month",
    ),
    WorkloadDimension(
        product_code="ecs",
        dimension="linux_general_purpose_instance_hour",
        usage_quantity=Decimal("730"),
        usage_unit="instance-hour",
        billing_unit="instance-hour",
    ),
    WorkloadDimension(
        product_code="ec2",
        dimension="linux_general_purpose_instance_hour",
        usage_quantity=Decimal("730"),
        usage_unit="instance-hour",
        billing_unit="instance-hour",
    ),
)


def generate_internal_tco(session: Session) -> dict[str, Any]:
    scenario = _ensure_scenario(session)
    now = datetime.now(UTC)
    providers = {
        provider.code: provider
        for provider in session.scalars(
            select(Provider).where(Provider.code.in_(["huawei_cloud", "aws", "aliyun"]))
        )
    }
    products = _products_by_provider(session)
    planned: list[tuple[Provider, Product, WorkloadDimension, PriceSnapshot | None]] = []
    for provider_code, provider in providers.items():
        for dimension in _dimensions_for_provider(provider_code):
            product = products.get((provider_code, dimension.product_code))
            if product is None or product.market_mode != scenario.market_mode:
                continue
            snapshot = _latest_snapshot_for_dimension(
                session,
                provider_id=provider.id,
                product_id=product.id,
                billing_unit=dimension.billing_unit,
                market_mode=scenario.market_mode,
                currency=scenario.target_currency,
            )
            planned.append((provider, product, dimension, snapshot))
    input_hash = _input_hash(scenario, planned, now)
    run_code = f"{RUN_CODE}_{input_hash[:16]}"
    existing = session.scalar(
        select(CostCalculationRun).where(CostCalculationRun.run_code == run_code)
    )
    if existing is not None:
        return {
            "scenario_code": scenario.scenario_code,
            "scenario_version": scenario.scenario_version,
            "run_code": existing.run_code,
            "status": existing.status,
            "line_items": session.scalar(
                select(func.count())
                .select_from(CostLineItem)
                .where(CostLineItem.run_id == existing.id)
            )
            or 0,
            "warnings": existing.warning_count,
            "results": session.scalar(
                select(func.count()).select_from(TCOResult).where(TCOResult.run_id == existing.id)
            )
            or 0,
            "created": False,
        }
    run = CostCalculationRun(
        scenario_id=scenario.id,
        run_code=run_code,
        rule_version=RULE_VERSION,
        price_snapshot_cutoff=now,
        started_at=now,
        status=CostCalculationRunStatus.PARTIAL.value,
        currency="USD",
        provider_count=len({provider.id for provider, _, _, _ in planned}),
        line_item_count=0,
        warning_count=0,
        error_count=0,
        content_hash="pending",
    )
    session.add(run)
    session.flush()

    line_items: list[CostLineItem] = []
    for provider, product, dimension, snapshot in planned:
        line_items.append(
            _line_item_for_dimension(
                run=run,
                provider=provider,
                product=product,
                dimension=dimension,
                snapshot=snapshot,
            )
        )
    session.add_all(line_items)
    session.flush()
    results = _results_from_line_items(run, scenario, line_items)
    for result in results:
        session.add(result)
    run.line_item_count = len(line_items)
    run.warning_count = sum(1 for item in line_items if item.warning or item.missing_reason)
    run.error_count = 0
    run.completed_at = datetime.now(UTC)
    run.status = (
        CostCalculationRunStatus.SUCCEEDED.value
        if run.warning_count == 0
        else CostCalculationRunStatus.PARTIAL.value
    )
    run.content_hash = _run_hash(line_items)
    session.commit()
    return {
        "scenario_code": scenario.scenario_code,
        "scenario_version": scenario.scenario_version,
        "run_code": run.run_code,
        "status": run.status,
        "line_items": len(line_items),
        "warnings": run.warning_count,
        "results": len(results),
        "created": True,
    }


def _ensure_scenario(session: Session) -> PricingScenario:
    scenario = session.scalar(
        select(PricingScenario).where(
            PricingScenario.scenario_code == SCENARIO_CODE,
            PricingScenario.scenario_version == SCENARIO_VERSION,
        )
    )
    if scenario is not None:
        return scenario
    scenario = PricingScenario(
        scenario_code=SCENARIO_CODE,
        scenario_version=SCENARIO_VERSION,
        name="Internal price readiness 1 TiB storage-month scenario",
        market_mode=MarketMode.INTERNATIONAL.value,
        billing_period="monthly",
        target_currency="USD",
        workload_profile={
            "storage_gb_month": "1024",
            "compute_instance_hours": "730",
            "usage_policy": "Prices with missing evidence remain missing.",
        },
        assumptions={
            "tax": "Taxes, duties, VAT, discounts, credits, and support fees are excluded.",
            "currency": "No cross-currency conversion is performed in Week 9.",
            "eligibility": "Internal readiness output only; not customer eligible.",
        },
        status=PricingScenarioStatus.ACTIVE.value,
    )
    session.add(scenario)
    session.flush()
    return scenario


def _input_hash(
    scenario: PricingScenario,
    planned: list[tuple[Provider, Product, WorkloadDimension, PriceSnapshot | None]],
    now: datetime,
) -> str:
    payload = {
        "rule_version": RULE_VERSION,
        "freshness_day": now.date().isoformat(),
        "scenario": [
            scenario.scenario_code,
            scenario.scenario_version,
            scenario.market_mode,
            scenario.target_currency,
            scenario.workload_profile,
        ],
        "dimensions": [
            [
                provider.id,
                product.id,
                dimension.dimension,
                str(dimension.usage_quantity),
                snapshot.id if snapshot else None,
                str(snapshot.unit_price) if snapshot else None,
                snapshot.captured_at if snapshot else None,
                snapshot.evidence.source_document.content_hash if snapshot else None,
            ]
            for provider, product, dimension, snapshot in planned
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _products_by_provider(session: Session) -> dict[tuple[str, str], Product]:
    rows = session.execute(
        select(Product, Provider).join(Provider, Product.provider_id == Provider.id)
    ).all()
    return {(provider.code, product.code): product for product, provider in rows}


def _dimensions_for_provider(provider_code: str) -> tuple[WorkloadDimension, ...]:
    if provider_code == "huawei_cloud":
        return tuple(item for item in WORKLOAD_DIMENSIONS if item.product_code in {"ecs", "obs"})
    if provider_code == "aws":
        return tuple(item for item in WORKLOAD_DIMENSIONS if item.product_code in {"ec2", "s3"})
    if provider_code == "aliyun":
        return tuple(item for item in WORKLOAD_DIMENSIONS if item.product_code in {"ecs", "oss"})
    return ()


def _latest_snapshot_for_dimension(
    session: Session,
    *,
    provider_id: int,
    product_id: int,
    billing_unit: str,
    market_mode: str,
    currency: str,
    region_code: str | None = None,
    provider_price_code: str | None = None,
) -> PriceSnapshot | None:
    # A shared billing unit is not a resource identity or evidence of regional sale.
    if not region_code or not provider_price_code:
        return None
    snapshot = session.scalar(
        select(PriceSnapshot)
        .join(PriceSKU, PriceSnapshot.price_sku_id == PriceSKU.id)
        .join(Region, PriceSKU.region_id == Region.id)
        .where(
            PriceSKU.provider_id == provider_id,
            PriceSKU.product_id == product_id,
            PriceSKU.billing_unit == billing_unit,
            PriceSKU.currency == currency,
            Region.market_mode == market_mode,
            Region.code == region_code,
            PriceSKU.provider_price_code == provider_price_code,
            PriceSnapshot.minimum_quantity.is_(None) | (PriceSnapshot.minimum_quantity == 0),
            PriceSnapshot.maximum_quantity.is_(None),
        )
        .order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc())
    )
    if snapshot is not None and not _aws_policy_current(session, snapshot):
        return None
    return snapshot


def _aws_policy_current(session: Session, snapshot: PriceSnapshot) -> bool:
    from cloud_expert.pricing.consumption import aws_price_current, is_aws_price

    if is_aws_price(snapshot):
        return aws_price_current(session, snapshot)
    return True


def _line_item_for_dimension(
    *,
    run: CostCalculationRun,
    provider: Provider,
    product: Product,
    dimension: WorkloadDimension,
    snapshot: PriceSnapshot | None,
) -> CostLineItem:
    if dimension.usage_quantity < 0:
        raise ValueError("usage quantity cannot be negative")
    if snapshot is not None and (
        (
            snapshot.minimum_quantity is not None
            and dimension.usage_quantity < snapshot.minimum_quantity
        )
        or (
            snapshot.maximum_quantity is not None
            and dimension.usage_quantity > snapshot.maximum_quantity
        )
    ):
        item = _line_item_for_dimension(
            run=run, provider=provider, product=product, dimension=dimension, snapshot=None
        )
        item.missing_reason = (
            "Usage exceeds the evidenced price tier; additional tiers are required."
        )
        return item
    if snapshot is None:
        return CostLineItem(
            run_id=run.id,
            provider_id=provider.id,
            product_id=product.id,
            dimension=dimension.dimension,
            usage_quantity=dimension.usage_quantity,
            usage_unit=dimension.usage_unit,
            tax_status=TaxStatus.TAX_UNKNOWN.value,
            assumptions={"missing_prices_are_not_zero": True},
            missing_reason=(
                "No PriceSnapshot with official evidence is available for this "
                f"{provider.code}/{product.code} dimension."
            ),
        )
    price_sku = snapshot.price_sku
    amount = (snapshot.unit_price * dimension.usage_quantity).quantize(Decimal("0.00000001"))
    return CostLineItem(
        run_id=run.id,
        provider_id=provider.id,
        product_id=product.id,
        price_sku_id=price_sku.id,
        price_snapshot_id=snapshot.id,
        evidence_id=snapshot.evidence_id,
        dimension=dimension.dimension,
        usage_quantity=dimension.usage_quantity,
        usage_unit=dimension.usage_unit,
        unit_price=snapshot.unit_price,
        currency=price_sku.currency,
        amount=amount,
        tax_status=TaxStatus.TAX_INCLUDED.value
        if price_sku.tax_included
        else TaxStatus.TAX_EXCLUDED.value,
        formula=f"{dimension.usage_quantity} {dimension.usage_unit} * {snapshot.unit_price} {price_sku.currency}/{price_sku.billing_unit}",
        assumptions={"missing_prices_are_not_zero": True},
        warning=(
            "Official price snapshot is not fresh."
            if price_snapshot_freshness(snapshot) != FreshnessStatus.FRESH.value
            else None
            if price_sku.currency == run.currency
            else "Price currency differs from calculation currency."
        ),
    )


def _results_from_line_items(
    run: CostCalculationRun,
    scenario: PricingScenario,
    line_items: list[CostLineItem],
) -> list[TCOResult]:
    results: list[TCOResult] = []
    groups: dict[tuple[int, int], list[CostLineItem]] = defaultdict(list)
    for item in line_items:
        groups[(item.provider_id, item.product_id)].append(item)
    for (provider_id, product_id), items in groups.items():
        missing = sum(item.amount is None for item in items)
        warnings = sum(bool(item.warning or item.missing_reason) for item in items)
        currencies_match = all(item.currency in {None, scenario.target_currency} for item in items)
        dimensions = {item.dimension for item in items}
        duplicate_dimension = len(dimensions) != len(items)
        declared = scenario.workload_profile.get("required_cost_dimensions", [])
        scope_complete = bool(
            isinstance(declared, list) and declared and set(declared) == dimensions
        )
        fresh_states = {price_snapshot_freshness(item.price_snapshot) for item in items}
        freshness = (
            FreshnessStatus.FRESH.value
            if fresh_states == {FreshnessStatus.FRESH.value}
            else FreshnessStatus.STALE.value
            if FreshnessStatus.STALE.value in fresh_states
            else FreshnessStatus.UNKNOWN.value
        )
        known_subtotal = sum(
            (item.amount for item in items if item.amount is not None), Decimal("0")
        )
        subtotal = (
            known_subtotal
            if currencies_match and not duplicate_dimension and missing < len(items)
            else None
        )
        total = subtotal if missing == 0 else None
        # A pre-tax estimate is not proof that tax equals zero.
        tax_known = all(item.tax_status == TaxStatus.TAX_INCLUDED.value for item in items)
        pre_tax_scope = (scenario.assumptions or {}).get("tax_scope") == "pre_tax" and all(
            item.tax_status == TaxStatus.TAX_EXCLUDED.value for item in items
        )
        tax_scope_matches = (
            pre_tax_scope
            or tax_known
            and (scenario.assumptions or {}).get("tax_scope") != "pre_tax"
        )
        if not currencies_match or duplicate_dimension:
            status = TCOCompletenessStatus.REQUIRES_REVIEW.value
            warnings += 1
        elif missing:
            status = TCOCompletenessStatus.MISSING_PRICE.value
        elif (
            scope_complete
            and freshness == FreshnessStatus.FRESH.value
            and tax_scope_matches
            and not warnings
        ):
            status = TCOCompletenessStatus.COMPLETE.value
        else:
            status = TCOCompletenessStatus.PARTIAL.value
        results.append(
            TCOResult(
                run_id=run.id,
                scenario_id=scenario.id,
                provider_id=provider_id,
                product_id=product_id,
                subtotal=subtotal,
                tax_amount=None,
                total=total,
                currency=scenario.target_currency,
                billing_period=scenario.billing_period,
                completeness_status=status,
                freshness_status=freshness,
                comparability_status=(
                    ComparabilityStatus.PARTIAL.value
                    if total is not None
                    else ComparabilityStatus.NEEDS_REVIEW.value
                ),
                warning_count=warnings,
                missing_price_count=missing,
            )
        )
    return results


def _run_hash(line_items: list[CostLineItem]) -> str:
    payload = [
        {
            "provider_id": item.provider_id,
            "product_id": item.product_id,
            "dimension": item.dimension,
            "usage_quantity": str(item.usage_quantity),
            "unit_price": str(item.unit_price),
            "amount": str(item.amount),
            "missing_reason": item.missing_reason,
        }
        for item in line_items
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def tco_result_currently_complete(session: Session, result: TCOResult) -> bool:
    from cloud_expert.pricing.scoped_tco import RULE_VERSION as SCOPED_RULE
    from cloud_expert.pricing.scoped_tco import scoped_tco_result_currently_complete

    if result.run is not None and result.run.rule_version == SCOPED_RULE:
        return scoped_tco_result_currently_complete(session, result)
    if result.completeness_status != TCOCompletenessStatus.COMPLETE.value:
        return False
    items = list(
        session.scalars(
            select(CostLineItem).where(
                CostLineItem.run_id == result.run_id,
                CostLineItem.provider_id == result.provider_id,
                CostLineItem.product_id == result.product_id,
            )
        )
    )
    if not items:
        return False
    for item in items:
        snapshot = item.price_snapshot
        if (
            snapshot is None
            or item.usage_quantity is None
            or item.unit_price is None
            or item.unit_price != snapshot.unit_price
            or item.evidence_id != snapshot.evidence_id
            or snapshot.price_sku.provider_id != item.provider_id
            or snapshot.price_sku.product_id != item.product_id
            or snapshot.price_sku.currency != item.currency
            or item.price_sku_id != snapshot.price_sku_id
            or item.usage_unit != snapshot.price_sku.billing_unit
            or item.tax_status
            != (
                TaxStatus.TAX_INCLUDED.value
                if snapshot.price_sku.tax_included
                else TaxStatus.TAX_EXCLUDED.value
            )
            or snapshot.minimum_quantity is not None
            and item.usage_quantity < snapshot.minimum_quantity
            or snapshot.maximum_quantity is not None
            and item.usage_quantity > snapshot.maximum_quantity
            or item.amount
            != (item.usage_quantity * item.unit_price).quantize(Decimal("0.00000001"))
        ):
            return False
        from cloud_expert.pricing.huawei_promotion import RULE, bounded_quote_valid

        if snapshot.evidence.parser_rule == RULE and not bounded_quote_valid(session, snapshot):
            return False
        from cloud_expert.pricing.aliyun_promotion import RULE as CATALOG_RULE
        from cloud_expert.pricing.aliyun_promotion import catalog_price_valid

        if snapshot.evidence.parser_rule == CATALOG_RULE and (
            (result.scenario.assumptions or {}).get("price_basis") != "catalog_reference"
            or not catalog_price_valid(session, snapshot)
        ):
            return False
        if not _aws_policy_current(session, snapshot):
            return False
    recalculated = _results_from_line_items(result.run, result.scenario, items)[0]
    return (
        recalculated.completeness_status == TCOCompletenessStatus.COMPLETE.value
        and recalculated.total == result.total
        and recalculated.subtotal == result.subtotal
    )
