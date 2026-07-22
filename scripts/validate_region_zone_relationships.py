import argparse
import json

import _bootstrap  # noqa: F401
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from cloud_expert.database.enums import AvailabilityStatus
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import AvailabilityZone, Region, ZoneAvailability
from cloud_expert.database.session import SessionLocal

POSITIVE_STATUSES = {
    AvailabilityStatus.AVAILABLE.value,
    AvailabilityStatus.PREVIEW.value,
    AvailabilityStatus.LIMITED.value,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate region and zone relationships.")
    parser.add_argument("--provider", default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        zone_errors, zone_count = _validate_zones(session, provider_code=args.provider)
        availability_errors, availability_count = _validate_zone_availability(
            session,
            provider_code=args.provider,
        )

    errors = zone_errors + availability_errors
    result = {
        "provider": args.provider,
        "zones_checked": zone_count,
        "zone_availability_checked": availability_count,
        "errors": len(errors),
        "error_messages": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def _validate_zones(
    session: Session,
    *,
    provider_code: str | None,
) -> tuple[list[str], int]:
    statement = (
        select(AvailabilityZone, Region, Provider)
        .join(Provider, AvailabilityZone.provider_id == Provider.id)
        .outerjoin(Region, AvailabilityZone.region_id == Region.id)
        .order_by(Provider.code, AvailabilityZone.zone_code)
    )
    if provider_code:
        statement = statement.where(Provider.code == provider_code)
    rows = session.execute(statement).all()

    errors: list[str] = []
    for zone, region, provider in rows:
        if region is None:
            errors.append(f"zone:{zone.zone_code}: missing parent region.")
            continue
        inferred_region = _region_code_for_zone(zone.zone_code)
        if inferred_region != region.code:
            errors.append(
                f"zone:{zone.zone_code}: inferred region {inferred_region} "
                f"does not match region {region.code}."
            )
        if zone.cloud_partition_id != region.cloud_partition_id:
            errors.append(f"zone:{zone.zone_code}: cloud_partition_id differs from region.")
        if zone.market_mode != region.market_mode:
            errors.append(f"zone:{zone.zone_code}: market_mode differs from region.")
        if provider.code == "aliyun" and zone.evidence_id is None:
            errors.append(f"zone:{zone.zone_code}: missing evidence_id.")
    return errors, len(rows)


def _validate_zone_availability(
    session: Session,
    *,
    provider_code: str | None,
) -> tuple[list[str], int]:
    product_provider = aliased(Provider)
    zone_provider = aliased(Provider)
    statement = (
        select(ZoneAvailability, AvailabilityZone, Region, Product, product_provider, zone_provider)
        .outerjoin(AvailabilityZone, ZoneAvailability.availability_zone_id == AvailabilityZone.id)
        .outerjoin(Region, ZoneAvailability.region_id == Region.id)
        .outerjoin(Product, ZoneAvailability.product_id == Product.id)
        .outerjoin(product_provider, Product.provider_id == product_provider.id)
        .outerjoin(zone_provider, AvailabilityZone.provider_id == zone_provider.id)
        .order_by(product_provider.code, Product.code, ZoneAvailability.id)
    )
    if provider_code:
        statement = statement.where(product_provider.code == provider_code)
    rows = session.execute(statement).all()

    errors: list[str] = []
    for availability, zone, region, product, product_provider_row, zone_provider_row in rows:
        identity = f"zone_availability:{availability.id}"
        if zone is None:
            errors.append(f"{identity}: missing availability_zone row.")
            continue
        if region is None:
            errors.append(f"{identity}: missing region row.")
            continue
        if product is None:
            errors.append(f"{identity}: missing product row.")
            continue
        if product_provider_row is None or zone_provider_row is None:
            errors.append(f"{identity}: missing provider relationship.")
            continue
        if availability.region_id != zone.region_id:
            errors.append(f"{identity}: region_id does not match zone.region_id.")
        if availability.cloud_partition_id != zone.cloud_partition_id:
            errors.append(f"{identity}: cloud_partition_id does not match zone.")
        if product_provider_row.code != zone_provider_row.code:
            errors.append(
                f"{identity}: product provider {product_provider_row.code} "
                f"differs from zone provider {zone_provider_row.code}."
            )
        if (
            availability.availability_status in POSITIVE_STATUSES
            and availability.evidence_id is None
        ):
            errors.append(f"{identity}: positive availability status is missing evidence_id.")
    return errors, len(rows)


def _region_code_for_zone(zone_code: str) -> str:
    return zone_code.rsplit("-", 1)[0] if "-" in zone_code else zone_code


if __name__ == "__main__":
    raise SystemExit(main())
