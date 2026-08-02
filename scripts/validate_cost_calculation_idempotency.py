from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, inspect, select

from cloud_expert.database.models.tco import CostCalculationRun, CostLineItem, TCOResult
from cloud_expert.database.session import SessionLocal, make_engine


def validate_cost_calculation_idempotency() -> dict[str, Any]:
    engine = make_engine()
    inspector = inspect(engine)
    expected_tables = {"pricing_scenario", "cost_calculation_run", "cost_line_item", "tco_result"}
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(expected_tables - existing_tables)
    if missing_tables:
        return {
            "expected_tables": sorted(expected_tables),
            "missing_tables": missing_tables,
            "calculation_runs_checked": 0,
            "cost_line_items": 0,
            "tco_results": 0,
            "errors": ["TCO calculation tables are not present; idempotency cannot be evaluated"],
            "valid": False,
        }

    with SessionLocal() as session:
        runs = session.scalar(select(func.count()).select_from(CostCalculationRun)) or 0
        line_items = session.scalar(select(func.count()).select_from(CostLineItem)) or 0
        results = session.scalar(select(func.count()).select_from(TCOResult)) or 0
        duplicate_run_codes = session.execute(
            select(CostCalculationRun.run_code)
            .group_by(CostCalculationRun.run_code)
            .having(func.count() > 1)
        ).all()
        missing_without_reason = (
            session.scalar(
                select(func.count())
                .select_from(CostLineItem)
                .where(CostLineItem.amount.is_(None), CostLineItem.missing_reason.is_(None))
            )
            or 0
        )
        priced_without_snapshot = (
            session.scalar(
                select(func.count())
                .select_from(CostLineItem)
                .where(
                    CostLineItem.amount.is_not(None),
                    CostLineItem.price_snapshot_id.is_(None),
                )
            )
            or 0
        )
        missing_treated_as_zero = (
            session.scalar(
                select(func.count())
                .select_from(CostLineItem)
                .where(CostLineItem.missing_reason.is_not(None), CostLineItem.amount == 0)
            )
            or 0
        )

    errors: list[str] = []
    if runs == 0:
        errors.append("no cost calculation runs are present")
    if line_items == 0:
        errors.append("no cost line items are present")
    if results == 0:
        errors.append("no TCO results are present")
    if duplicate_run_codes:
        errors.append("duplicate cost calculation run_code values are present")
    if missing_without_reason:
        errors.append("missing-price line items must include a missing_reason")
    if priced_without_snapshot:
        errors.append("priced line items must link to a PriceSnapshot")
    if missing_treated_as_zero:
        errors.append("missing prices must not be represented as zero amounts")
    return {
        "expected_tables": sorted(expected_tables),
        "missing_tables": missing_tables,
        "calculation_runs_checked": runs,
        "cost_line_items": line_items,
        "tco_results": results,
        "duplicate_run_codes": [row[0] for row in duplicate_run_codes],
        "missing_without_reason": missing_without_reason,
        "priced_without_snapshot": priced_without_snapshot,
        "missing_treated_as_zero": missing_treated_as_zero,
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    result = validate_cost_calculation_idempotency()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
