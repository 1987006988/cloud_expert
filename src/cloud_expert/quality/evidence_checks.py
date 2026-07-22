from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import AvailabilityStatus
from cloud_expert.database.models.parsing import ParsedFieldCandidate
from cloud_expert.database.models.product_extension import ProductSLA, ServiceTier
from cloud_expert.database.models.region import Availability, AvailabilityZone, ZoneAvailability
from cloud_expert.database.models.specification import ProductSpecification


def count_missing_evidence_links(session: Session) -> int:
    missing_specifications = session.scalar(
        select(func.count())
        .select_from(ProductSpecification)
        .where(ProductSpecification.evidence_id.is_(None))
    )
    missing_candidates = session.scalar(
        select(func.count())
        .select_from(ParsedFieldCandidate)
        .where(ParsedFieldCandidate.evidence_id.is_(None))
    )
    missing_tiers = session.scalar(
        select(func.count()).select_from(ServiceTier).where(ServiceTier.evidence_id.is_(None))
    )
    missing_sla = session.scalar(
        select(func.count()).select_from(ProductSLA).where(ProductSLA.evidence_id.is_(None))
    )
    missing_availability = session.scalar(
        select(func.count())
        .select_from(Availability)
        .where(
            Availability.availability_status.in_(
                (
                    AvailabilityStatus.AVAILABLE.value,
                    AvailabilityStatus.PREVIEW.value,
                    AvailabilityStatus.LIMITED.value,
                )
            ),
            Availability.evidence_id.is_(None),
        )
    )
    missing_zones = session.scalar(
        select(func.count())
        .select_from(AvailabilityZone)
        .where(AvailabilityZone.evidence_id.is_(None))
    )
    missing_zone_availability = session.scalar(
        select(func.count())
        .select_from(ZoneAvailability)
        .where(
            ZoneAvailability.availability_status.in_(
                (
                    AvailabilityStatus.AVAILABLE.value,
                    AvailabilityStatus.PREVIEW.value,
                    AvailabilityStatus.LIMITED.value,
                )
            ),
            ZoneAvailability.evidence_id.is_(None),
        )
    )
    return (
        int(missing_specifications or 0)
        + int(missing_candidates or 0)
        + int(missing_tiers or 0)
        + int(missing_sla or 0)
        + int(missing_availability or 0)
        + int(missing_zones or 0)
        + int(missing_zone_availability or 0)
    )
