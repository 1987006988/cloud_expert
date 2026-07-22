from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import (
    Availability,
    AvailabilityZone,
    Region,
    ZoneAvailability,
)
from cloud_expert.ingestion.providers.aliyun.common import (
    ALIYUN_PUBLIC_CN_PARTITION,
    is_mainland_region_code,
)


def count_partition_region_violations(
    session: Session,
    *,
    provider_code: str,
    partition_code: str,
) -> int:
    if provider_code == "aliyun" and partition_code == ALIYUN_PUBLIC_CN_PARTITION:
        region_codes = session.scalars(
            select(Region.code)
            .join(Provider, Region.provider_id == Provider.id)
            .join(
                CloudPartition,
                Region.cloud_partition_id == CloudPartition.id,
                isouter=True,
            )
            .where(
                Provider.code == provider_code,
                CloudPartition.partition_code == partition_code,
            )
        ).all()
        return sum(1 for code in region_codes if not is_mainland_region_code(code))
    if provider_code != "aws" or partition_code != "aws":
        return 0
    return int(
        session.scalar(
            select(func.count())
            .select_from(Region)
            .join(Provider, Region.provider_id == Provider.id)
            .join(
                CloudPartition,
                Region.cloud_partition_id == CloudPartition.id,
                isouter=True,
            )
            .where(
                Provider.code == provider_code,
                CloudPartition.partition_code == partition_code,
                Region.code.like("cn-%") | Region.code.like("us-gov-%"),
            )
        )
        or 0
    )


def count_partition_zone_violations(
    session: Session,
    *,
    provider_code: str,
    partition_code: str,
) -> int:
    if provider_code != "aliyun" or partition_code != ALIYUN_PUBLIC_CN_PARTITION:
        return 0
    rows = session.execute(
        select(AvailabilityZone.zone_code, Region.code)
        .join(Provider, AvailabilityZone.provider_id == Provider.id)
        .join(Region, AvailabilityZone.region_id == Region.id)
        .join(
            CloudPartition,
            AvailabilityZone.cloud_partition_id == CloudPartition.id,
            isouter=True,
        )
        .where(
            Provider.code == provider_code,
            CloudPartition.partition_code == partition_code,
        )
    ).all()
    violations = 0
    for zone_code, region_code in rows:
        inferred_region = _region_code_for_zone(zone_code)
        if not is_mainland_region_code(region_code) or inferred_region != region_code:
            violations += 1
    return violations


def count_product_availability(
    session: Session,
    *,
    provider_code: str,
    product_code: str,
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Availability)
            .join(Product, Availability.product_id == Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
        )
        or 0
    )


def count_product_zone_availability(
    session: Session,
    *,
    provider_code: str,
    product_code: str,
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ZoneAvailability)
            .join(Product, ZoneAvailability.product_id == Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
        )
        or 0
    )


def count_product_regions(
    session: Session,
    *,
    provider_code: str,
    product_code: str,
) -> int:
    return int(
        session.scalar(
            select(func.count(func.distinct(Region.id)))
            .select_from(Availability)
            .join(Region, Availability.region_id == Region.id)
            .join(Product, Availability.product_id == Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
        )
        or 0
    )


def count_product_zones(
    session: Session,
    *,
    provider_code: str,
    product_code: str,
) -> int:
    return int(
        session.scalar(
            select(func.count(func.distinct(AvailabilityZone.id)))
            .select_from(ZoneAvailability)
            .join(AvailabilityZone, ZoneAvailability.availability_zone_id == AvailabilityZone.id)
            .join(Product, ZoneAvailability.product_id == Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
        )
        or 0
    )


def _region_code_for_zone(zone_code: str) -> str:
    return zone_code.rsplit("-", 1)[0] if "-" in zone_code else zone_code
