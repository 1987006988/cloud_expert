import argparse
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.ingestion import IngestionRun
from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.models.product import SKU, Product, ProductCategory
from cloud_expert.database.models.product_extension import ProductFamily, ProductSLA, ServiceTier
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import (
    Availability,
    AvailabilityZone,
    Region,
    ZoneAvailability,
)
from cloud_expert.database.models.review import DataQualityIssue, ReviewItem
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.database.session import SessionLocal

DEFAULT_SOURCE_DBS = (
    Path("test_outputs/week3_huawei_acceptance.sqlite"),
    Path("test_outputs/week4_aws_acceptance.sqlite"),
    Path("test_outputs/week5_aliyun_acceptance_v2.sqlite"),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Week 6 combined projection from prior acceptance databases."
    )
    parser.add_argument("--source-db", action="append", type=Path, default=None)
    args = parser.parse_args()
    source_paths = tuple(args.source_db or DEFAULT_SOURCE_DBS)

    imported: list[dict[str, object]] = []
    with SessionLocal() as target_session:
        for source_path in source_paths:
            imported.append(_import_source_database(source_path, target_session))
        target_session.commit()
    print(json.dumps({"sources": imported}, ensure_ascii=False, indent=2, default=str))
    return 0


def _import_source_database(source_path: Path, target_session: Session) -> dict[str, object]:
    if not source_path.exists():
        return {"source": str(source_path), "error": "source database not found"}
    engine = create_engine(f"sqlite:///{source_path}", future=True)
    try:
        with Session(engine, future=True) as source_session:
            provider_map = _copy_providers(source_session, target_session)
            category_map = _copy_categories(source_session, target_session)
            source_document_map = _copy_source_documents(
                source_session,
                target_session,
                provider_map,
            )
            snapshot_map = _copy_snapshot_records(
                source_session,
                target_session,
                source_document_map,
            )
            ingestion_count = _copy_ingestion_runs(source_session, target_session, snapshot_map)
            evidence_map = _copy_evidence(
                source_session,
                target_session,
                source_document_map,
                snapshot_map,
            )
            product_map = _copy_products(
                source_session,
                target_session,
                provider_map,
                category_map,
            )
            partition_map = _copy_cloud_partitions(source_session, target_session, provider_map)
            region_map = _copy_regions(
                source_session,
                target_session,
                provider_map,
                partition_map,
            )
            sku_map = _copy_skus(source_session, target_session, product_map)
            definition_map = _copy_definitions(source_session, target_session, category_map)
            family_count = _copy_product_families(
                source_session,
                target_session,
                product_map,
                evidence_map,
            )
            tier_count = _copy_service_tiers(
                source_session,
                target_session,
                product_map,
                evidence_map,
            )
            sla_count = _copy_product_slas(
                source_session,
                target_session,
                product_map,
                evidence_map,
            )
            availability_count = _copy_availability(
                source_session,
                target_session,
                product_map,
                region_map,
                partition_map,
                evidence_map,
            )
            zone_map = _copy_availability_zones(
                source_session,
                target_session,
                provider_map,
                region_map,
                partition_map,
                evidence_map,
            )
            zone_availability_count = _copy_zone_availability(
                source_session,
                target_session,
                product_map,
                region_map,
                zone_map,
                partition_map,
                evidence_map,
            )
            parsing_run_map = _copy_parsing_runs(
                source_session,
                target_session,
                source_document_map,
                snapshot_map,
            )
            parsed_candidate_map = _copy_parsed_field_candidates(
                source_session,
                target_session,
                parsing_run_map,
                source_document_map,
                snapshot_map,
                evidence_map,
            )
            spec_count = _copy_specifications(
                source_session,
                target_session,
                product_map,
                sku_map,
                definition_map,
                evidence_map,
            )
            review_count = _copy_review_items(
                source_session,
                target_session,
                parsing_run_map,
                parsed_candidate_map,
                evidence_map,
            )
            data_quality_count = _copy_data_quality_issues(
                source_session,
                target_session,
                parsing_run_map,
                evidence_map,
            )
    finally:
        engine.dispose()
    return {
        "source": str(source_path),
        "providers": len(provider_map),
        "categories": len(category_map),
        "source_documents": len(source_document_map),
        "snapshot_records": len(snapshot_map),
        "ingestion_runs": ingestion_count,
        "evidence": len(evidence_map),
        "products": len(product_map),
        "cloud_partitions": len(partition_map),
        "regions": len(region_map),
        "skus": len(sku_map),
        "specification_definitions": len(definition_map),
        "product_families": family_count,
        "service_tiers": tier_count,
        "product_slas": sla_count,
        "availability": availability_count,
        "availability_zones": len(zone_map),
        "zone_availability": zone_availability_count,
        "parsing_runs": len(parsing_run_map),
        "parsed_field_candidates": len(parsed_candidate_map),
        "product_specifications": spec_count,
        "review_items": review_count,
        "data_quality_issues": data_quality_count,
    }


def _copy_providers(source_session: Session, target_session: Session) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for provider in source_session.scalars(select(Provider).order_by(Provider.id)):
        target = target_session.scalar(select(Provider).where(Provider.code == provider.code))
        if target is None:
            target = Provider(
                code=provider.code,
                name=provider.name,
                display_name=provider.display_name,
                provider_type=provider.provider_type,
                official_website=provider.official_website,
                is_active=provider.is_active,
            )
            target_session.add(target)
            target_session.flush()
        id_map[provider.id] = target.id
    return id_map


def _copy_categories(source_session: Session, target_session: Session) -> dict[int, int]:
    id_map: dict[int, int] = {}
    categories = list(source_session.scalars(select(ProductCategory).order_by(ProductCategory.id)))
    for category in categories:
        parent_id = None if category.parent_id is None else id_map.get(category.parent_id)
        target = target_session.scalar(
            select(ProductCategory).where(ProductCategory.code == category.code)
        )
        if target is None:
            target = ProductCategory(
                code=category.code,
                name=category.name,
                parent_id=parent_id,
                description=category.description,
            )
            target_session.add(target)
            target_session.flush()
        id_map[category.id] = target.id
    return id_map


def _copy_source_documents(
    source_session: Session,
    target_session: Session,
    provider_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    columns = _source_document_columns(source_session)
    selected_columns = ", ".join(
        column for column in _source_document_select_columns() if column in columns
    )
    rows = [
        dict(row)
        for row in source_session.execute(
            text(f"SELECT {selected_columns} FROM source_document ORDER BY id")
        ).mappings()
    ]
    for document in rows:
        target = target_session.scalar(
            select(SourceDocument).where(
                SourceDocument.url == document["url"],
                SourceDocument.content_hash == document["content_hash"],
            )
        )
        if target is None:
            target = SourceDocument(
                provider_id=provider_map[int(document["provider_id"])],
                source_type=str(document["source_type"]),
                title=str(document["title"]),
                url=str(document["url"]),
                cloud_partition=_optional_str(document, "cloud_partition"),
                language=_optional_str(document, "language"),
                authority_level=str(document["authority_level"]),
                content_hash=str(document["content_hash"]),
                storage_path=_optional_str(document, "storage_path"),
                mime_type=_optional_str(document, "mime_type"),
                http_status=_optional_int(document, "http_status"),
                is_current=_optional_bool(document, "is_current", default=True),
            )
            target_session.add(target)
            target_session.flush()
        id_map[int(document["id"])] = target.id
    return id_map


def _source_document_select_columns() -> tuple[str, ...]:
    return (
        "id",
        "provider_id",
        "source_type",
        "title",
        "url",
        "cloud_partition",
        "language",
        "authority_level",
        "content_hash",
        "storage_path",
        "mime_type",
        "http_status",
        "is_current",
    )


def _source_document_columns(source_session: Session) -> set[str]:
    return {
        str(row["name"])
        for row in source_session.execute(text("PRAGMA table_info(source_document)")).mappings()
    }


def _optional_str(row: Mapping[str, Any], key: str) -> str | None:
    value = row.get(key)
    return None if value is None else str(value)


def _optional_int(row: Mapping[str, Any], key: str) -> int | None:
    value = row.get(key)
    return None if value is None else int(value)


def _optional_bool(row: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = row.get(key)
    if value is None:
        return default
    return bool(value)


def _optional_datetime(row: Mapping[str, Any], key: str) -> datetime | None:
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _copy_evidence(
    source_session: Session,
    target_session: Session,
    source_document_map: dict[int, int],
    snapshot_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for evidence in source_session.scalars(select(Evidence).order_by(Evidence.id)):
        snapshot_record_id = (
            None
            if evidence.snapshot_record_id is None
            else snapshot_map.get(evidence.snapshot_record_id)
        )
        target = target_session.scalar(
            select(Evidence).where(
                Evidence.source_document_id == source_document_map[evidence.source_document_id],
                Evidence.locator == evidence.locator,
                Evidence.excerpt == evidence.excerpt,
                Evidence.parser_rule == evidence.parser_rule,
                Evidence.content_hash == evidence.content_hash,
                Evidence.snapshot_record_id == snapshot_record_id,
            )
        )
        if target is None:
            target = Evidence(
                source_document_id=source_document_map[evidence.source_document_id],
                section_title=evidence.section_title,
                page_title=evidence.page_title,
                locator=evidence.locator,
                excerpt=evidence.excerpt,
                evidence_type=evidence.evidence_type,
                snapshot_record_id=snapshot_record_id,
                content_hash=evidence.content_hash,
                parser_rule=evidence.parser_rule,
                confidence=evidence.confidence,
                review_status=evidence.review_status,
                reviewed_by=evidence.reviewed_by,
                reviewed_at=evidence.reviewed_at,
            )
            target_session.add(target)
            target_session.flush()
        id_map[evidence.id] = target.id
    return id_map


def _copy_snapshot_records(
    source_session: Session,
    target_session: Session,
    source_document_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    if not _has_table(source_session, "snapshot_record"):
        return id_map
    for snapshot in source_session.scalars(select(SnapshotRecord).order_by(SnapshotRecord.id)):
        previous_snapshot_id = (
            None
            if snapshot.previous_snapshot_id is None
            else id_map.get(snapshot.previous_snapshot_id)
        )
        target = target_session.scalar(
            select(SnapshotRecord).where(
                SnapshotRecord.source_id == snapshot.source_id,
                SnapshotRecord.content_hash == snapshot.content_hash,
            )
        )
        if target is None:
            target = SnapshotRecord(
                source_document_id=source_document_map[snapshot.source_document_id],
                source_id=snapshot.source_id,
                content_hash=snapshot.content_hash,
                normalized_hash=snapshot.normalized_hash,
                normalization_version=snapshot.normalization_version,
                storage_path=snapshot.storage_path,
                manifest_path=snapshot.manifest_path,
                content_type=snapshot.content_type,
                content_length_bytes=snapshot.content_length_bytes,
                captured_at=snapshot.captured_at,
                previous_snapshot_id=previous_snapshot_id,
                change_status=snapshot.change_status,
                is_current=snapshot.is_current,
            )
            target_session.add(target)
            target_session.flush()
        id_map[snapshot.id] = target.id
    return id_map


def _copy_ingestion_runs(
    source_session: Session,
    target_session: Session,
    snapshot_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "ingestion_run"):
        return 0
    count = 0
    for run in source_session.scalars(select(IngestionRun).order_by(IngestionRun.id)):
        snapshot_id = None if run.snapshot_id is None else snapshot_map.get(run.snapshot_id)
        target = target_session.scalar(
            select(IngestionRun).where(
                IngestionRun.source_id == run.source_id,
                IngestionRun.run_type == run.run_type,
                IngestionRun.started_at == run.started_at,
                IngestionRun.snapshot_id == snapshot_id,
            )
        )
        if target is None:
            target_session.add(
                IngestionRun(
                    source_id=run.source_id,
                    run_type=run.run_type,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    status=run.status,
                    requested_url=run.requested_url,
                    final_url=run.final_url,
                    http_status=run.http_status,
                    content_type=run.content_type,
                    bytes_downloaded=run.bytes_downloaded,
                    retry_count=run.retry_count,
                    duration_ms=run.duration_ms,
                    snapshot_id=snapshot_id,
                    error_code=run.error_code,
                    error_message=run.error_message,
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_products(
    source_session: Session,
    target_session: Session,
    provider_map: dict[int, int],
    category_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for product in source_session.scalars(select(Product).order_by(Product.id)):
        target = target_session.scalar(
            select(Product).where(
                Product.provider_id == provider_map[product.provider_id],
                Product.code == product.code,
            )
        )
        if target is None:
            target = Product(
                provider_id=provider_map[product.provider_id],
                category_id=category_map[product.category_id],
                market_mode=product.market_mode,
                code=product.code,
                official_name=product.official_name,
                display_name=product.display_name,
                description=product.description,
                product_status=product.product_status,
                official_url=product.official_url,
                documentation_url=product.documentation_url,
                first_seen_at=product.first_seen_at,
                last_verified_at=product.last_verified_at,
                metadata_json=product.metadata_json,
            )
            target_session.add(target)
            target_session.flush()
        id_map[product.id] = target.id
    return id_map


def _copy_cloud_partitions(
    source_session: Session,
    target_session: Session,
    provider_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    if not _has_table(source_session, "cloud_partition"):
        return id_map
    for partition in source_session.scalars(select(CloudPartition).order_by(CloudPartition.id)):
        target = target_session.scalar(
            select(CloudPartition).where(
                CloudPartition.provider_id == provider_map[partition.provider_id],
                CloudPartition.partition_code == partition.partition_code,
            )
        )
        if target is None:
            target = CloudPartition(
                provider_id=provider_map[partition.provider_id],
                partition_code=partition.partition_code,
                partition_name=partition.partition_name,
                market_mode=partition.market_mode,
                geography_scope=partition.geography_scope,
                is_active=partition.is_active,
            )
            target_session.add(target)
            target_session.flush()
        id_map[partition.id] = target.id
    return id_map


def _copy_regions(
    source_session: Session,
    target_session: Session,
    provider_map: dict[int, int],
    partition_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    if not _has_table(source_session, "region"):
        return id_map
    columns = _table_columns(source_session, "region")
    rows = _select_rows(source_session, "region")
    for region in rows:
        cloud_partition_id = _mapped_optional_id(
            region,
            "cloud_partition_id",
            partition_map,
            columns,
        )
        target = target_session.scalar(
            select(Region).where(
                Region.provider_id == provider_map[int(region["provider_id"])],
                Region.code == str(region["code"]),
            )
        )
        if target is None:
            target = Region(
                provider_id=provider_map[int(region["provider_id"])],
                cloud_partition_id=cloud_partition_id,
                code=str(region["code"]),
                name=str(region["name"]),
                country_code=str(region["country_code"]),
                geography=_optional_str(region, "geography"),
                market_mode=str(region["market_mode"]),
                is_active=_optional_bool(region, "is_active", default=True),
            )
            target_session.add(target)
            target_session.flush()
        id_map[int(region["id"])] = target.id
    return id_map


def _copy_skus(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for sku in source_session.scalars(select(SKU).order_by(SKU.id)):
        target = target_session.scalar(
            select(SKU).where(
                SKU.product_id == product_map[sku.product_id],
                SKU.provider_sku_code == sku.provider_sku_code,
            )
        )
        if target is None:
            target = SKU(
                product_id=product_map[sku.product_id],
                provider_sku_code=sku.provider_sku_code,
                name=sku.name,
                sku_family=sku.sku_family,
                architecture=sku.architecture,
                operating_system=sku.operating_system,
                status=sku.status,
            )
            target_session.add(target)
            target_session.flush()
        id_map[sku.id] = target.id
    return id_map


def _copy_product_families(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "product_family"):
        return 0
    count = 0
    for family in source_session.scalars(select(ProductFamily).order_by(ProductFamily.id)):
        target = target_session.scalar(
            select(ProductFamily).where(
                ProductFamily.product_id == product_map[family.product_id],
                ProductFamily.family_code == family.family_code,
            )
        )
        if target is None:
            target_session.add(
                ProductFamily(
                    product_id=product_map[family.product_id],
                    family_code=family.family_code,
                    family_name=family.family_name,
                    family_type=family.family_type,
                    workload_type=family.workload_type,
                    architecture=family.architecture,
                    processor_vendor=family.processor_vendor,
                    processor_model_raw=family.processor_model_raw,
                    generation=family.generation,
                    status=family.status,
                    evidence_id=_map_optional_value(family.evidence_id, evidence_map),
                    review_status=family.review_status,
                    metadata_json=family.metadata_json,
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_service_tiers(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "service_tier"):
        return 0
    count = 0
    for tier in source_session.scalars(select(ServiceTier).order_by(ServiceTier.id)):
        target = target_session.scalar(
            select(ServiceTier).where(
                ServiceTier.product_id == product_map[tier.product_id],
                ServiceTier.tier_code == tier.tier_code,
            )
        )
        if target is None:
            target_session.add(
                ServiceTier(
                    product_id=product_map[tier.product_id],
                    tier_code=tier.tier_code,
                    official_name=tier.official_name,
                    access_pattern=tier.access_pattern,
                    minimum_storage_duration_days=tier.minimum_storage_duration_days,
                    retrieval_characteristics=tier.retrieval_characteristics,
                    availability_design=tier.availability_design,
                    durability_design=tier.durability_design,
                    supported_region=tier.supported_region,
                    status=tier.status,
                    evidence_id=_map_optional_value(tier.evidence_id, evidence_map),
                    review_status=tier.review_status,
                    metadata_json=tier.metadata_json,
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_product_slas(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "product_sla"):
        return 0
    count = 0
    for sla in source_session.scalars(select(ProductSLA).order_by(ProductSLA.id)):
        evidence_id = evidence_map[sla.evidence_id]
        target = target_session.scalar(
            select(ProductSLA).where(
                ProductSLA.product_id == product_map[sla.product_id],
                ProductSLA.record_type == sla.record_type,
                ProductSLA.scope == sla.scope,
                ProductSLA.raw_value == sla.raw_value,
                ProductSLA.evidence_id == evidence_id,
            )
        )
        if target is None:
            target_session.add(
                ProductSLA(
                    product_id=product_map[sla.product_id],
                    record_type=sla.record_type,
                    metric_name=sla.metric_name,
                    scope=sla.scope,
                    raw_value=sla.raw_value,
                    normalized_percentage=sla.normalized_percentage,
                    effective_notes=sla.effective_notes,
                    evidence_id=evidence_id,
                    review_status=sla.review_status,
                    valid_from=sla.valid_from,
                    valid_to=sla.valid_to,
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_availability(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
    region_map: dict[int, int],
    partition_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "availability"):
        return 0
    columns = _table_columns(source_session, "availability")
    count = 0
    for availability in _select_rows(source_session, "availability"):
        source_region_id = int(availability["region_id"])
        if source_region_id not in region_map:
            continue
        cloud_partition_id = _mapped_optional_id(
            availability,
            "cloud_partition_id",
            partition_map,
            columns,
        )
        evidence_id = _mapped_optional_id(availability, "evidence_id", evidence_map, columns)
        target_type = str(availability["target_type"]) if "target_type" in columns else "product"
        target_code = str(availability["target_code"]) if "target_code" in columns else "product"
        target = target_session.scalar(
            select(Availability).where(
                Availability.product_id == product_map[int(availability["product_id"])],
                Availability.region_id == region_map[source_region_id],
                Availability.target_type == target_type,
                Availability.target_code == target_code,
            )
        )
        if target is None:
            target_session.add(
                Availability(
                    product_id=product_map[int(availability["product_id"])],
                    region_id=region_map[source_region_id],
                    cloud_partition_id=cloud_partition_id,
                    target_type=target_type,
                    target_code=target_code,
                    availability_status=str(availability["availability_status"]),
                    public_preview=_optional_bool(availability, "public_preview", default=False),
                    generally_available=_optional_bool(
                        availability,
                        "generally_available",
                        default=False,
                    ),
                    available_since=_optional_datetime(availability, "available_since"),
                    unavailable_since=_optional_datetime(availability, "unavailable_since"),
                    last_verified_at=_optional_datetime(availability, "last_verified_at"),
                    evidence_id=evidence_id,
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_availability_zones(
    source_session: Session,
    target_session: Session,
    provider_map: dict[int, int],
    region_map: dict[int, int],
    partition_map: dict[int, int],
    evidence_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    if not _has_table(source_session, "availability_zone"):
        return id_map
    columns = _table_columns(source_session, "availability_zone")
    for zone in _select_rows(source_session, "availability_zone"):
        source_region_id = int(zone["region_id"])
        if source_region_id not in region_map:
            continue
        target = target_session.scalar(
            select(AvailabilityZone).where(
                AvailabilityZone.provider_id == provider_map[int(zone["provider_id"])],
                AvailabilityZone.zone_code == str(zone["zone_code"]),
            )
        )
        if target is None:
            target = AvailabilityZone(
                provider_id=provider_map[int(zone["provider_id"])],
                region_id=region_map[source_region_id],
                cloud_partition_id=_mapped_optional_id(
                    zone,
                    "cloud_partition_id",
                    partition_map,
                    columns,
                ),
                zone_code=str(zone["zone_code"]),
                zone_name=str(zone["zone_name"]),
                market_mode=str(zone["market_mode"]),
                is_active=_optional_bool(zone, "is_active", default=True),
                evidence_id=_mapped_optional_id(zone, "evidence_id", evidence_map, columns),
            )
            target_session.add(target)
            target_session.flush()
        id_map[int(zone["id"])] = target.id
    return id_map


def _copy_zone_availability(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
    region_map: dict[int, int],
    zone_map: dict[int, int],
    partition_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "zone_availability"):
        return 0
    columns = _table_columns(source_session, "zone_availability")
    count = 0
    for availability in _select_rows(source_session, "zone_availability"):
        source_region_id = int(availability["region_id"])
        source_zone_id = int(availability["availability_zone_id"])
        if source_region_id not in region_map or source_zone_id not in zone_map:
            continue
        target = target_session.scalar(
            select(ZoneAvailability).where(
                ZoneAvailability.product_id == product_map[int(availability["product_id"])],
                ZoneAvailability.availability_zone_id == zone_map[source_zone_id],
                ZoneAvailability.target_type == str(availability["target_type"]),
                ZoneAvailability.target_code == str(availability["target_code"]),
            )
        )
        if target is None:
            target_session.add(
                ZoneAvailability(
                    product_id=product_map[int(availability["product_id"])],
                    region_id=region_map[source_region_id],
                    availability_zone_id=zone_map[source_zone_id],
                    cloud_partition_id=_mapped_optional_id(
                        availability,
                        "cloud_partition_id",
                        partition_map,
                        columns,
                    ),
                    target_type=str(availability["target_type"]),
                    target_code=str(availability["target_code"]),
                    availability_status=str(availability["availability_status"]),
                    public_preview=_optional_bool(availability, "public_preview", default=False),
                    generally_available=_optional_bool(
                        availability,
                        "generally_available",
                        default=False,
                    ),
                    available_since=_optional_datetime(availability, "available_since"),
                    unavailable_since=_optional_datetime(availability, "unavailable_since"),
                    last_verified_at=_optional_datetime(availability, "last_verified_at"),
                    evidence_id=_mapped_optional_id(
                        availability, "evidence_id", evidence_map, columns
                    ),
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_definitions(
    source_session: Session,
    target_session: Session,
    category_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    for definition in source_session.scalars(
        select(SpecificationDefinition).order_by(SpecificationDefinition.id)
    ):
        target = target_session.scalar(
            select(SpecificationDefinition).where(SpecificationDefinition.code == definition.code)
        )
        if target is None:
            target = SpecificationDefinition(
                code=definition.code,
                name=definition.name,
                category_id=category_map[definition.category_id],
                data_type=definition.data_type,
                canonical_unit=definition.canonical_unit,
                description=definition.description,
                is_required=definition.is_required,
            )
            target_session.add(target)
            target_session.flush()
        id_map[definition.id] = target.id
    return id_map


def _copy_specifications(
    source_session: Session,
    target_session: Session,
    product_map: dict[int, int],
    sku_map: dict[int, int],
    definition_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    count = 0
    for spec in source_session.scalars(
        select(ProductSpecification).order_by(ProductSpecification.id)
    ):
        target_product_id = product_map[spec.product_id]
        target_sku_id = None if spec.sku_id is None else sku_map[spec.sku_id]
        target_definition_id = definition_map[spec.definition_id]
        target_evidence_id = evidence_map[spec.evidence_id]
        target = target_session.scalar(
            select(ProductSpecification).where(
                ProductSpecification.product_id == target_product_id,
                ProductSpecification.sku_id == target_sku_id,
                ProductSpecification.definition_id == target_definition_id,
                ProductSpecification.evidence_id == target_evidence_id,
                ProductSpecification.raw_value == spec.raw_value,
                ProductSpecification.raw_unit == spec.raw_unit,
            )
        )
        if target is None:
            target_session.add(
                ProductSpecification(
                    product_id=target_product_id,
                    sku_id=target_sku_id,
                    definition_id=target_definition_id,
                    numeric_value=spec.numeric_value,
                    text_value=spec.text_value,
                    boolean_value=spec.boolean_value,
                    raw_value=spec.raw_value,
                    raw_unit=spec.raw_unit,
                    canonical_value=spec.canonical_value,
                    canonical_unit=spec.canonical_unit,
                    evidence_id=target_evidence_id,
                    valid_from=spec.valid_from,
                    valid_to=spec.valid_to,
                    last_verified_at=spec.last_verified_at,
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_parsing_runs(
    source_session: Session,
    target_session: Session,
    source_document_map: dict[int, int],
    snapshot_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    if not _has_table(source_session, "parsing_run"):
        return id_map
    for run in source_session.scalars(select(ParsingRun).order_by(ParsingRun.id)):
        snapshot_record_id = _map_optional_value(run.snapshot_record_id, snapshot_map)
        source_document_id = _map_optional_value(run.source_document_id, source_document_map)
        target = target_session.scalar(
            select(ParsingRun).where(
                ParsingRun.source_id == run.source_id,
                ParsingRun.snapshot_record_id == snapshot_record_id,
                ParsingRun.source_document_id == source_document_id,
                ParsingRun.parser_name == run.parser_name,
                ParsingRun.parser_version == run.parser_version,
                ParsingRun.started_at == run.started_at,
            )
        )
        if target is None:
            target = ParsingRun(
                source_id=run.source_id,
                snapshot_record_id=snapshot_record_id,
                source_document_id=source_document_id,
                parser_name=run.parser_name,
                parser_version=run.parser_version,
                started_at=run.started_at,
                completed_at=run.completed_at,
                status=run.status,
                records_found=run.records_found,
                fields_found=run.fields_found,
                evidence_created=run.evidence_created,
                review_items_created=run.review_items_created,
                error_message=run.error_message,
            )
            target_session.add(target)
            target_session.flush()
        id_map[run.id] = target.id
    return id_map


def _copy_parsed_field_candidates(
    source_session: Session,
    target_session: Session,
    parsing_run_map: dict[int, int],
    source_document_map: dict[int, int],
    snapshot_map: dict[int, int],
    evidence_map: dict[int, int],
) -> dict[int, int]:
    id_map: dict[int, int] = {}
    if not _has_table(source_session, "parsed_field_candidate"):
        return id_map
    for candidate in source_session.scalars(
        select(ParsedFieldCandidate).order_by(ParsedFieldCandidate.id)
    ):
        target_parsing_run_id = parsing_run_map[candidate.parsing_run_id]
        target = target_session.scalar(
            select(ParsedFieldCandidate).where(
                ParsedFieldCandidate.parsing_run_id == target_parsing_run_id,
                ParsedFieldCandidate.field_code == candidate.field_code,
                ParsedFieldCandidate.target_table == candidate.target_table,
                ParsedFieldCandidate.target_identity == candidate.target_identity,
                ParsedFieldCandidate.value_hash == candidate.value_hash,
            )
        )
        if target is None:
            target = ParsedFieldCandidate(
                parsing_run_id=target_parsing_run_id,
                source_document_id=source_document_map[candidate.source_document_id],
                snapshot_record_id=_map_optional_value(
                    candidate.snapshot_record_id,
                    snapshot_map,
                ),
                evidence_id=_map_optional_value(candidate.evidence_id, evidence_map),
                target_table=candidate.target_table,
                target_identity=candidate.target_identity,
                field_code=candidate.field_code,
                raw_value=candidate.raw_value,
                raw_unit=candidate.raw_unit,
                normalized_value=candidate.normalized_value,
                canonical_unit=candidate.canonical_unit,
                locator=candidate.locator,
                excerpt=candidate.excerpt,
                confidence=candidate.confidence,
                review_status=candidate.review_status,
                parser_rule=candidate.parser_rule,
                value_hash=candidate.value_hash,
            )
            target_session.add(target)
            target_session.flush()
        id_map[candidate.id] = target.id
    return id_map


def _copy_review_items(
    source_session: Session,
    target_session: Session,
    parsing_run_map: dict[int, int],
    parsed_candidate_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "review_item"):
        return 0
    count = 0
    for item in source_session.scalars(select(ReviewItem).order_by(ReviewItem.id)):
        evidence_id = _map_optional_value(item.evidence_id, evidence_map)
        target = target_session.scalar(
            select(ReviewItem).where(
                ReviewItem.item_type == item.item_type,
                ReviewItem.provider_code == item.provider_code,
                ReviewItem.product_code == item.product_code,
                ReviewItem.field_code == item.field_code,
                ReviewItem.reason == item.reason,
                ReviewItem.raw_value == item.raw_value,
                ReviewItem.evidence_id == evidence_id,
            )
        )
        if target is None:
            target_session.add(
                ReviewItem(
                    item_type=item.item_type,
                    severity=item.severity,
                    status=item.status,
                    provider_code=item.provider_code,
                    product_code=item.product_code,
                    field_code=item.field_code,
                    reason=item.reason,
                    raw_value=item.raw_value,
                    suggested_action=item.suggested_action,
                    parsing_run_id=_map_optional_value(item.parsing_run_id, parsing_run_map),
                    parsed_field_candidate_id=_map_optional_value(
                        item.parsed_field_candidate_id,
                        parsed_candidate_map,
                    ),
                    evidence_id=evidence_id,
                    resolved_at=item.resolved_at,
                    resolved_by=item.resolved_by,
                )
            )
            count += 1
    target_session.flush()
    return count


def _copy_data_quality_issues(
    source_session: Session,
    target_session: Session,
    parsing_run_map: dict[int, int],
    evidence_map: dict[int, int],
) -> int:
    if not _has_table(source_session, "data_quality_issue"):
        return 0
    count = 0
    for issue in source_session.scalars(select(DataQualityIssue).order_by(DataQualityIssue.id)):
        evidence_id = _map_optional_value(issue.evidence_id, evidence_map)
        target = target_session.scalar(
            select(DataQualityIssue).where(
                DataQualityIssue.provider_code == issue.provider_code,
                DataQualityIssue.product_code == issue.product_code,
                DataQualityIssue.issue_type == issue.issue_type,
                DataQualityIssue.message == issue.message,
                DataQualityIssue.field_code == issue.field_code,
                DataQualityIssue.evidence_id == evidence_id,
            )
        )
        if target is None:
            target_session.add(
                DataQualityIssue(
                    provider_code=issue.provider_code,
                    product_code=issue.product_code,
                    issue_type=issue.issue_type,
                    severity=issue.severity,
                    status=issue.status,
                    message=issue.message,
                    field_code=issue.field_code,
                    parsing_run_id=_map_optional_value(issue.parsing_run_id, parsing_run_map),
                    evidence_id=evidence_id,
                )
            )
            count += 1
    target_session.flush()
    return count


def _has_table(source_session: Session, table_name: str) -> bool:
    return bool(
        source_session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).first()
    )


def _table_columns(source_session: Session, table_name: str) -> set[str]:
    return {
        str(row["name"])
        for row in source_session.execute(text(f"PRAGMA table_info({table_name})")).mappings()
    }


def _select_rows(source_session: Session, table_name: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in source_session.execute(
            text(f"SELECT * FROM {table_name} ORDER BY id")
        ).mappings()
    ]


def _map_optional_value(value: int | None, id_map: dict[int, int]) -> int | None:
    if value is None:
        return None
    return id_map.get(value)


def _mapped_optional_id(
    row: Mapping[str, Any],
    key: str,
    id_map: dict[int, int],
    columns: set[str],
) -> int | None:
    if key not in columns:
        return None
    value = row.get(key)
    if value is None:
        return None
    return id_map.get(int(value))


if __name__ == "__main__":
    raise SystemExit(main())
