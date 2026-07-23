from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.session import SessionLocal


def validate_price_skus() -> dict[str, Any]:
    with SessionLocal() as session:
        price_skus = session.scalar(select(func.count()).select_from(PriceSKU)) or 0
        price_snapshots = session.scalar(select(func.count()).select_from(PriceSnapshot)) or 0
        sku_without_snapshots = (
            session.scalar(
                select(func.count())
                .select_from(PriceSKU)
                .outerjoin(PriceSnapshot, PriceSnapshot.price_sku_id == PriceSKU.id)
                .where(PriceSnapshot.id.is_(None))
            )
            or 0
        )
    errors: list[str] = []
    if price_skus == 0:
        errors.append("no PriceSKU rows are present")
    if price_snapshots == 0:
        errors.append("no PriceSnapshot rows are present")
    if sku_without_snapshots:
        errors.append("one or more PriceSKU rows have no PriceSnapshot")
    return {
        "price_skus": price_skus,
        "price_snapshots": price_snapshots,
        "sku_without_snapshots": sku_without_snapshots,
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    result = validate_price_skus()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
