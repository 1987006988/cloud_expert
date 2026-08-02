from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
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
from cloud_expert.database.models.tco import (
    CostCalculationRun,
    CostLineItem,
    PricingScenario,
    TCOResult,
)

RULE_VERSION = "week09_tco_v1"
SCENARIO_CODE = "internal_price_readiness_storage_1tb_month"
SCENARIO_VERSION = "2026-07-23"
RUN_CODE = "week09_price_readiness_20260723"


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
    _delete_existing_run(session, scenario)
    now = datetime.now(UTC)
    providers = {
        provider.code: provider
        for provider in session.scalars(
            select(Provider).where(Provider.code.in_(["huawei_cloud", "aws", "aliyun"]))
        )
    }
    products = _products_by_provider(session)
    run = CostCalculationRun(
        scenario_id=scenario.id,
        run_code=RUN_CODE,
        rule_version=RULE_VERSION,
        price_snapshot_cutoff=now,
        started_at=now,
        status=CostCalculationRunStatus.PARTIAL.value,
        currency="USD",
        provider_count=len(providers),
        line_item_count=0,
        warning_count=0,
        error_count=0,
        content_hash="pending",
    )
    session.add(run)
    session.flush()

    line_items: list[CostLineItem] = []
    for provider_code, provider in providers.items():
        for dimension in _dimensions_for_provider(provider_code):
            product = products.get((provider_code, dimension.product_code))
            if product is None:
                continue
            snapshot = _latest_snapshot_for_dimension(
                session,
                provider_id=provider.id,
                product_id=product.id,
                billing_unit=dimension.billing_unit,
            )
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


def _delete_existing_run(session: Session, scenario: PricingScenario) -> None:
    run = session.scalar(select(CostCalculationRun).where(CostCalculationRun.run_code == RUN_CODE))
    if run is None:
        return
    session.execute(delete(TCOResult).where(TCOResult.run_id == run.id))
    session.execute(delete(CostLineItem).where(CostLineItem.run_id == run.id))
    session.execute(delete(CostCalculationRun).where(CostCalculationRun.id == run.id))
    session.flush()


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
) -> PriceSnapshot | None:
    return session.scalar(
        select(PriceSnapshot)
        .join(PriceSKU, PriceSnapshot.price_sku_id == PriceSKU.id)
        .where(
            PriceSKU.provider_id == provider_id,
            PriceSKU.product_id == product_id,
            PriceSKU.billing_unit == billing_unit,
        )
        .order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc())
    )


def _line_item_for_dimension(
    *,
    run: CostCalculationRun,
    provider: Provider,
    product: Product,
    dimension: WorkloadDimension,
    snapshot: PriceSnapshot | None,
) -> CostLineItem:
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
        warning=None if price_sku.currency == "USD" else "Currency not converted to USD.",
    )


def _results_from_line_items(
    run: CostCalculationRun,
    scenario: PricingScenario,
    line_items: list[CostLineItem],
) -> list[TCOResult]:
    results: list[TCOResult] = []
    for item in line_items:
        missing = 1 if item.amount is None else 0
        warnings = 1 if item.warning or item.missing_reason else 0
        status = (
            TCOCompletenessStatus.MISSING_PRICE.value
            if item.amount is None
            else TCOCompletenessStatus.COMPLETE.value
        )
        results.append(
            TCOResult(
                run_id=run.id,
                scenario_id=scenario.id,
                provider_id=item.provider_id,
                product_id=item.product_id,
                subtotal=item.amount,
                tax_amount=Decimal("0.00000000") if item.amount is not None else None,
                total=item.amount,
                currency=item.currency or scenario.target_currency,
                billing_period=scenario.billing_period,
                completeness_status=status,
                freshness_status=FreshnessStatus.FRESH.value
                if item.amount is not None
                else FreshnessStatus.UNKNOWN.value,
                comparability_status=(
                    ComparabilityStatus.PARTIAL.value
                    if item.amount is not None
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
