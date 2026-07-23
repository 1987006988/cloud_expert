from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.session import SessionLocal


def check_price_freshness() -> dict[str, Any]:
    now = datetime.now(UTC)
    counts = {"current": 0, "due_soon": 0, "stale": 0, "historical": 0, "unknown": 0}
    with SessionLocal() as session:
        snapshots = session.scalars(select(PriceSnapshot)).all()
    for snapshot in snapshots:
        captured = snapshot.captured_at
        if captured is None:
            counts["unknown"] += 1
            continue
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=UTC)
        age_days = (now - captured).days
        if snapshot.effective_to is not None and snapshot.effective_to < now:
            counts["historical"] += 1
        elif age_days > 14:
            counts["stale"] += 1
        elif age_days > 11:
            counts["due_soon"] += 1
        else:
            counts["current"] += 1
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
