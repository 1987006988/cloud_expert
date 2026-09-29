from __future__ import annotations

import json

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.models.region import Availability, Region
from cloud_expert.database.session import SessionLocal


def validate_regions() -> dict[str, object]:
    with SessionLocal() as session:
        regions = session.scalars(select(Region)).all()
        no_partition = [region.code for region in regions if region.cloud_partition is None]
        unknown_country = [region.code for region in regions if region.country_code == "ZZ"]
        market_mismatch = [
            region.code
            for region in regions
            if region.cloud_partition is not None
            and region.cloud_partition.market_mode != region.market_mode
        ]
        no_availability_evidence = [
            region.code
            for region in regions
            if not session.scalar(
                select(func.count())
                .select_from(Availability)
                .where(Availability.region_id == region.id, Availability.evidence_id.is_not(None))
            )
        ]
    return {
        "regions": len(regions),
        "no_partition": no_partition,
        "unknown_country": unknown_country,
        "market_mismatch": market_mismatch,
        "no_availability_evidence": no_availability_evidence,
        "valid": bool(regions)
        and not (no_partition or unknown_country or market_mismatch or no_availability_evidence),
    }


def main() -> int:
    result = validate_regions()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
