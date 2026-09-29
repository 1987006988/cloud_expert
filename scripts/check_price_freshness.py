from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.freshness import price_snapshot_freshness


def check_price_freshness() -> dict[str, Any]:
    counts = {"current": 0, "due_soon": 0, "stale": 0, "historical": 0, "unknown": 0}
    with SessionLocal() as session:
        snapshots = session.scalars(select(PriceSnapshot)).all()
    for snapshot in snapshots:
        status = price_snapshot_freshness(snapshot)
        counts["current" if status == "fresh" else status] += 1
    errors = ["no price snapshots available for freshness evaluation"] if not snapshots else []
    return {
        "price_freshness_counts": counts,
        "price_snapshots": len(snapshots),
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    result = check_price_freshness()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
