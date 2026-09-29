"""Reproducible domestic cost details; missing components never become zero."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.tco import CostCalculationRun, PricingScenario
from cloud_expert.pricing.freshness import price_snapshot_freshness
from cloud_expert.pricing.huawei_promotion import RULE, bounded_quote_valid
from cloud_expert.pricing.tco import (
    WorkloadDimension,
    _line_item_for_dimension,
    _results_from_line_items,
    _run_hash,
)

VERSION = "domestic_bounded_price_readiness_v1"
DIMENSIONS = {
    "ecs": (
        ("compute_instance_hours", "730", "instance-hour", "Duration"),
        ("system_disk_gb_month", "100", "GB-month", None),
        ("outbound_gb", "100", "GB", None),
        ("support_month", "1", "month", None),
    ),
    "obs": (
        ("standard_storage_gb_month", "1024", "GB-month", None),
        ("get_requests", "10000", "request", "get"),
        ("put_requests", "10000", "request", "put"),
        ("outbound_gb", "100", "GB", "download.external"),
        ("support_month", "1", "month", None),
    ),
}


def generate_domestic_readiness(session: Session) -> dict[str, Any]:
    """Caller owns commit/rollback; this scenario is not a customer recommendation."""
    now = datetime.now(UTC)
    snapshots = list(session.scalars(select(PriceSnapshot).order_by(PriceSnapshot.id.desc())))
    valid = [
        price
        for price in snapshots
        if price.evidence.parser_rule == RULE
        and bounded_quote_valid(session, price)
        and price_snapshot_freshness(price, now=now) == "fresh"
    ]
    output: list[dict[str, Any]] = []
    for code, dimensions in DIMENSIONS.items():
        product = session.scalar(
            select(Product)
            .join(Provider)
            .where(
                Provider.code == "huawei_cloud",
                Product.code == code,
                Product.market_mode == "domestic",
            )
        )
        if product is None:
            continue
        workload = {
            "region": "cn-north-4",
            "country_code": "CN",
            "required_cost_dimensions": [row[0] for row in dimensions],
            "quantities": {row[0]: row[1] for row in dimensions},
            "resource_spec": "c6.large.2.linux" if code == "ecs" else "obs",
            "usage_origin": "internal_assumptions_not_customer_data",
        }
        assumptions = {
            "tax_scope": "tax_included",
            "customer_eligible": False,
            "purpose": "Component price readiness, not full architecture TCO or vendor comparison",
            "support_policy": "No free support assumption; fee and eligibility remain unknown",
        }
        scenario_code = f"internal_huawei_cn_north_4_{code}_monthly_readiness"
        scenario = session.scalar(
            select(PricingScenario).where(
                PricingScenario.scenario_code == scenario_code,
                PricingScenario.scenario_version == VERSION,
            )
        )
        if scenario is None:
            scenario = PricingScenario(
                scenario_code=scenario_code,
                scenario_version=VERSION,
                name=f"Internal Huawei {code.upper()} domestic price readiness",
                market_mode="domestic",
                billing_period="monthly",
                target_currency="CNY",
                workload_profile=workload,
                assumptions=assumptions,
                status="active",
            )
            session.add(scenario)
            session.flush()
        elif (
            scenario.workload_profile != workload
            or scenario.assumptions != assumptions
            or scenario.market_mode != "domestic"
            or scenario.target_currency != "CNY"
        ):
            raise ValueError("Existing readiness scenario differs; create a new version")
        planned = []
        for dimension, quantity, unit, factor in dimensions:
            matched = next(
                (
                    price
                    for price in valid
                    if factor is not None
                    and price.price_sku.product_id == product.id
                    and price.price_sku.billing_unit == unit
                    and price.minimum_quantity == price.maximum_quantity == Decimal(quantity)
                    and json.loads(price.evidence.excerpt)["usage_factor"] == factor
                    and json.loads(price.evidence.excerpt)["resource_spec"]
                    == workload["resource_spec"]
                ),
                None,
            )
            planned.append(
                (WorkloadDimension(code, dimension, Decimal(quantity), unit, unit), matched)
            )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "rule": VERSION,
                    "day": now.date().isoformat(),
                    "workload": workload,
                    "prices": [price.id if price else None for _, price in planned],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        run_code = f"{VERSION}_{code}_{fingerprint[:16]}"
        run = session.scalar(
            select(CostCalculationRun).where(CostCalculationRun.run_code == run_code)
        )
        created = run is None
        if run is None:
            run = CostCalculationRun(
                scenario_id=scenario.id,
                run_code=run_code,
                rule_version=VERSION,
                price_snapshot_cutoff=now,
                started_at=now,
                status="partial",
                currency="CNY",
                provider_count=1,
                line_item_count=0,
                warning_count=0,
                error_count=0,
                content_hash="pending",
            )
            session.add(run)
            session.flush()
            items = [
                _line_item_for_dimension(
                    run=run,
                    provider=product.provider,
                    product=product,
                    dimension=dimension,
                    snapshot=price,
                )
                for dimension, price in planned
            ]
            session.add_all(items)
            session.flush()
            results = _results_from_line_items(run, scenario, items)
            session.add_all(results)
            run.line_item_count = len(items)
            run.warning_count = sum(bool(item.warning or item.missing_reason) for item in items)
            run.completed_at = datetime.now(UTC)
            run.content_hash = _run_hash(items)
            run.status = (
                "succeeded"
                if all(r.completeness_status == "complete" for r in results)
                else "partial"
            )
            session.flush()
        output.append(
            {
                "product": code,
                "scenario_id": scenario.id,
                "run_id": run.id,
                "created": created,
                "status": run.status,
                "currency": run.currency,
                "customer_eligible": False,
                "line_items": [
                    {
                        "dimension": item.dimension,
                        "quantity": str(item.usage_quantity),
                        "unit": item.usage_unit,
                        "amount": str(item.amount) if item.amount is not None else None,
                        "price_snapshot_id": item.price_snapshot_id,
                        "evidence_id": item.evidence_id,
                        "missing_reason": item.missing_reason,
                    }
                    for item in run.line_items
                ],
                "results": [
                    {
                        "id": result.id,
                        "status": result.completeness_status,
                        "known_subtotal": str(result.subtotal)
                        if result.subtotal is not None
                        else None,
                        "total": str(result.total) if result.total is not None else None,
                    }
                    for result in run.results
                ],
            }
        )
    return {"rule_version": VERSION, "runs": output}
