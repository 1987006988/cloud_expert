from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.region import Availability, Region
from cloud_expert.database.session import SessionLocal

RESOLUTIONS = {
    "ap-southeast-6": ("NZ", "New Zealand"),
    "ap-east-2": ("TW", "Taipei"),
}
REPORT_ROOT = Path("reports/market/region_country_resolution")


def resolve(*, apply: bool = False) -> dict[str, Any]:
    with SessionLocal() as session:
        changes: list[dict[str, Any]] = []
        regions: list[Region] = []
        for region_code, (country_code, location_name) in RESOLUTIONS.items():
            region = session.scalar(select(Region).where(Region.code == region_code))
            if region is None or region.provider.code != "aws":
                raise ValueError(f"AWS region missing or provider mismatch: {region_code}")
            if region.country_code == country_code:
                continue
            if region.country_code != "ZZ":
                raise ValueError(f"refusing to replace non-unknown country for {region_code}")
            availabilities = session.scalars(
                select(Availability).where(Availability.region_id == region.id)
            ).all()
            supporting = sorted(
                {
                    item.evidence.id
                    for item in availabilities
                    if item.evidence is not None
                    and item.evidence.snapshot_record_id is not None
                    and location_name in item.evidence.excerpt
                    and region_code in item.evidence.excerpt
                    and item.evidence.source_document.provider_id == region.provider_id
                }
            )
            if len(supporting) < 2:
                raise ValueError(f"insufficient independent snapshot evidence for {region_code}")
            changes.append(
                {
                    "region_id": region.id,
                    "region_code": region_code,
                    "previous_country_code": "ZZ",
                    "new_country_code": country_code,
                    "evidence_ids": supporting,
                    "source_urls": sorted(
                        {
                            item.evidence.source_document.url
                            for item in availabilities
                            if item.evidence is not None and item.evidence.id in supporting
                        }
                    ),
                }
            )
            regions.append(region)
        digest = sha256(json.dumps(changes, sort_keys=True).encode("utf-8")).hexdigest()
        result: dict[str, Any] = {
            "input_fingerprint": digest,
            "resolved_regions": len(changes),
            "changes": changes,
            "applied": apply,
        }
        if not apply:
            return result
        for region, change in zip(regions, changes, strict=True):
            region.country_code = change["new_country_code"]
        session.commit()
    report_dir = REPORT_ROOT / f"run_{digest[:12]}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation_results.json"
    if not report_path.exists():
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = resolve(apply=args.apply)
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
