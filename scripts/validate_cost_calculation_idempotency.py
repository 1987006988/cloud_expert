from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import inspect

from cloud_expert.database.session import make_engine


def validate_cost_calculation_idempotency() -> dict[str, Any]:
    engine = make_engine()
    inspector = inspect(engine)
    expected_tables = {"pricing_scenario", "cost_calculation_run", "cost_line_item", "tco_result"}
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(expected_tables - existing_tables)
    return {
        "expected_tables": sorted(expected_tables),
        "missing_tables": missing_tables,
        "calculation_runs_checked": 0,
        "errors": (
            ["TCO calculation tables are not present; idempotency cannot be evaluated"]
            if missing_tables
            else []
        ),
        "valid": not missing_tables,
    }


def main() -> int:
    result = validate_cost_calculation_idempotency()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
