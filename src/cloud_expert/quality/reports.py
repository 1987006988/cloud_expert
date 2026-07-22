import json
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ProductSLA, ServiceTier
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.review import ReviewItem
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.quality.consistency import count_low_confidence_fields
from cloud_expert.quality.coverage import calculate_coverage
from cloud_expert.quality.evidence_checks import count_missing_evidence_links
from cloud_expert.quality.partitions import (
    count_partition_region_violations,
    count_partition_zone_violations,
    count_product_availability,
    count_product_regions,
    count_product_zone_availability,
    count_product_zones,
)


def build_quality_report(
    session: Session,
    *,
    provider_code: str,
    product_code: str,
) -> dict[str, object]:
    product_filter = _parsed_product_filter(provider_code, product_code)
    observed_fields = set(
        session.scalars(
            select(ParsedFieldCandidate.field_code)
            .join(ParsingRun, ParsedFieldCandidate.parsing_run_id == ParsingRun.id)
            .where(product_filter)
        ).all()
    )
    evidence_ids = (
        select(ParsedFieldCandidate.evidence_id)
        .join(ParsingRun, ParsedFieldCandidate.parsing_run_id == ParsingRun.id)
        .where(product_filter, ParsedFieldCandidate.evidence_id.is_not(None))
        .distinct()
    )
    evidence_count = int(
        session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.id.in_(evidence_ids))
        )
        or 0
    )
    parsing_run_count = int(
        session.scalar(
            select(func.count())
            .select_from(ParsingRun)
            .where(ParsingRun.source_id.like(f"{provider_code}_{product_code}_%"))
        )
        or 0
    )
    coverage = calculate_coverage(product_code, observed_fields, provider_code)
    product_count = _count_product(session, provider_code, product_code)
    sku_count = _count_skus(session, provider_code, product_code)
    family_count = _count_families(session, provider_code, product_code)
    service_tier_count = _count_service_tiers(session, provider_code, product_code)
    review_count = int(
        session.scalar(
            select(func.count())
            .select_from(ReviewItem)
            .where(
                ReviewItem.provider_code == provider_code,
                ReviewItem.product_code == product_code,
            )
        )
        or 0
    )
    return {
        "provider_code": provider_code,
        "product_code": product_code,
        "product_records": product_count,
        "sku_records": sku_count,
        "product_family_records": family_count,
        "service_tier_records": service_tier_count,
        "region_records": count_product_regions(
            session,
            provider_code=provider_code,
            product_code=product_code,
        ),
        "availability_records": count_product_availability(
            session,
            provider_code=provider_code,
            product_code=product_code,
        ),
        "zone_records": count_product_zones(
            session,
            provider_code=provider_code,
            product_code=product_code,
        ),
        "zone_availability_records": count_product_zone_availability(
            session,
            provider_code=provider_code,
            product_code=product_code,
        ),
        "sla_records": _count_sla(session, provider_code, product_code),
        "parsing_runs": parsing_run_count,
        "evidence_records": evidence_count,
        "review_items": review_count,
        "missing_evidence_links": count_missing_evidence_links(session),
        "partition_region_violations": count_partition_region_violations(
            session,
            provider_code=provider_code,
            partition_code=_default_partition_code(provider_code),
        ),
        "partition_zone_violations": count_partition_zone_violations(
            session,
            provider_code=provider_code,
            partition_code=_default_partition_code(provider_code),
        ),
        "low_confidence_fields": count_low_confidence_fields(session, provider_code, product_code),
        "field_coverage": {
            "expected_fields": coverage.expected_fields,
            "observed_fields": coverage.observed_fields,
            "coverage_ratio": round(coverage.coverage_ratio, 4),
        },
        "human_review_completed": False,
    }


def write_quality_report(report: dict[str, object], output_path: Path) -> None:
    atomic_write_text(output_path, json.dumps(report, ensure_ascii=False, indent=2, default=str))


def _parsed_product_filter(provider_code: str, product_code: str) -> ColumnElement[bool]:
    return or_(
        ParsingRun.source_id.like(f"{provider_code}_{product_code}_%"),
        ParsedFieldCandidate.target_identity.like(f"%{product_code}%"),
    )


def _default_partition_code(provider_code: str) -> str:
    if provider_code == "aliyun":
        return "aliyun_public_cn"
    return "aws"


def _product_ids(session: Session, provider_code: str, product_code: str) -> list[int]:
    return list(
        session.scalars(
            select(Product.id)
            .join(Provider, Product.provider_id == Provider.id)
            .where(Provider.code == provider_code, Product.code == product_code)
        ).all()
    )


def _count_product(session: Session, provider_code: str, product_code: str) -> int:
    return len(_product_ids(session, provider_code, product_code))


def _count_skus(session: Session, provider_code: str, product_code: str) -> int:
    ids = _product_ids(session, provider_code, product_code)
    if not ids:
        return 0
    return int(
        session.scalar(select(func.count()).select_from(SKU).where(SKU.product_id.in_(ids))) or 0
    )


def _count_families(session: Session, provider_code: str, product_code: str) -> int:
    ids = _product_ids(session, provider_code, product_code)
    if not ids:
        return 0
    return int(
        session.scalar(
            select(func.count()).select_from(ProductFamily).where(ProductFamily.product_id.in_(ids))
        )
        or 0
    )


def _count_service_tiers(session: Session, provider_code: str, product_code: str) -> int:
    ids = _product_ids(session, provider_code, product_code)
    if not ids:
        return 0
    return int(
        session.scalar(
            select(func.count()).select_from(ServiceTier).where(ServiceTier.product_id.in_(ids))
        )
        or 0
    )


def _count_sla(session: Session, provider_code: str, product_code: str) -> int:
    ids = _product_ids(session, provider_code, product_code)
    if not ids:
        return 0
    return int(
        session.scalar(
            select(func.count()).select_from(ProductSLA).where(ProductSLA.product_id.in_(ids))
        )
        or 0
    )
