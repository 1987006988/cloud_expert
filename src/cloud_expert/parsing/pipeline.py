from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    AvailabilityStatus,
    ParserRunStatus,
    ProductFamilyType,
    ProductStatus,
    QualityIssueSeverity,
    ReviewItemStatus,
    ReviewItemType,
    ReviewStatus,
    SKUStatus,
    SLARecordType,
    SourceType,
)
from cloud_expert.database.models.cloud_partition import CloudPartition
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
from cloud_expert.database.models.review import ReviewItem
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.ingestion.providers.aliyun.common import (
    ALIYUN_PROVIDER_CODE,
    ALIYUN_PROVIDER_PROFILE,
    ALIYUN_PUBLIC_CN_PARTITION,
    ALIYUN_PUBLIC_CN_PARTITION_PROFILE,
)
from cloud_expert.ingestion.providers.aliyun.common import (
    parser_version_for_product as aliyun_parser_version_for_product,
)
from cloud_expert.ingestion.providers.aliyun.ecs.mappings import ALIYUN_ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aliyun.ecs.parser import (
    parse_ecs_document as parse_aliyun_ecs_document,
)
from cloud_expert.ingestion.providers.aliyun.oss.mappings import ALIYUN_OSS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aliyun.oss.parser import (
    parse_oss_document as parse_aliyun_oss_document,
)
from cloud_expert.ingestion.providers.aws.common import (
    AWS_COMMERCIAL_PARTITION,
    AWS_COMMERCIAL_PARTITION_PROFILE,
    AWS_PROVIDER_CODE,
    AWS_PROVIDER_PROFILE,
)
from cloud_expert.ingestion.providers.aws.common import (
    PARSER_VERSION as AWS_PARSER_VERSION,
)
from cloud_expert.ingestion.providers.aws.ec2.mappings import EC2_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.ec2.parser import parse_ec2_document
from cloud_expert.ingestion.providers.aws.s3.mappings import S3_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.s3.parser import parse_s3_document
from cloud_expert.ingestion.providers.huawei_cloud.common import (
    HUAWEI_CLOUD_PROVIDER_CODE,
)
from cloud_expert.ingestion.providers.huawei_cloud.common import (
    PARSER_VERSION as HUAWEI_PARSER_VERSION,
)
from cloud_expert.ingestion.providers.huawei_cloud.ecs.mappings import ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.ecs.parser import parse_ecs_document
from cloud_expert.ingestion.providers.huawei_cloud.obs.mappings import OBS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.obs.parser import parse_obs_document
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.normalization.ecs import infer_ecs_family_code
from cloud_expert.normalization.obs import normalize_storage_class_code
from cloud_expert.parsing.evidence import get_or_create_evidence
from cloud_expert.parsing.hashing import field_value_hash
from cloud_expert.parsing.html_adapter import load_html_document
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord, ParseSummary

PRODUCT_SPEC_DEFINITION_SETS = (
    ECS_SPEC_DEFINITIONS,
    OBS_SPEC_DEFINITIONS,
    EC2_SPEC_DEFINITIONS,
    S3_SPEC_DEFINITIONS,
    ALIYUN_ECS_SPEC_DEFINITIONS,
    ALIYUN_OSS_SPEC_DEFINITIONS,
)


def parse_registered_sources(
    session: Session,
    *,
    provider: str | None = None,
    product: str | None = None,
    source_id: str | None = None,
    registry_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> list[ParseSummary]:
    entries = load_registry_entries(registry_dir)
    if provider:
        entries = [entry for entry in entries if entry.provider_code == provider]
    if product:
        entries = [entry for entry in entries if entry.product_code == product]
    if source_id:
        entries = [entry for entry in entries if entry.source_id == source_id]
    else:
        entries = [entry for entry in entries if entry.enabled]
    store = SnapshotStore(raw_dir)
    summaries: list[ParseSummary] = []
    for entry in entries:
        summaries.append(parse_source_entry(session, entry, store))
    return summaries


def parse_source_entry(
    session: Session,
    entry: SourceRegistryEntry,
    store: SnapshotStore,
) -> ParseSummary:
    started = datetime.now(UTC)
    latest = store.latest_manifest(entry)
    if latest is None:
        return ParseSummary(
            source_id=entry.source_id,
            product_code=entry.product_code or "unknown",
            status=ParserRunStatus.SKIPPED.value,
            error_message="No raw snapshot found for source.",
        )
    manifest, manifest_path = latest
    snapshot_record = session.scalar(
        select(SnapshotRecord).where(
            SnapshotRecord.source_id == entry.source_id,
            SnapshotRecord.content_hash == manifest.content_sha256,
        )
    )
    source_document = session.scalar(
        select(SourceDocument).where(
            SourceDocument.url == manifest.final_url,
            SourceDocument.content_hash == manifest.content_sha256,
        )
    )
    if source_document is None:
        return ParseSummary(
            source_id=entry.source_id,
            product_code=entry.product_code or "unknown",
            status=ParserRunStatus.SKIPPED.value,
            error_message="SourceDocument record is missing for snapshot.",
        )

    parser_name = _parser_name(entry)
    parsing_run = ParsingRun(
        source_id=entry.source_id,
        snapshot_record_id=snapshot_record.id if snapshot_record else None,
        source_document_id=source_document.id,
        parser_name=parser_name,
        parser_version=_parser_version(entry),
        started_at=started,
        status=ParserRunStatus.SKIPPED.value,
        records_found=0,
        fields_found=0,
        evidence_created=0,
        review_items_created=0,
    )
    session.add(parsing_run)
    session.flush()
    if manifest.content_type != "text/html":
        parsing_run.completed_at = datetime.now(UTC)
        parsing_run.status = ParserRunStatus.SKIPPED.value
        parsing_run.error_message = (
            f"Unsupported content type for product parser: {manifest.content_type}"
        )
        session.commit()
        return _summary(entry, parsing_run)

    html_path = store.raw_data_dir / manifest.storage_path
    document = load_html_document(html_path)
    records = _parse_records(entry, document, manifest.snapshot_id)
    if not records:
        parsing_run.completed_at = datetime.now(UTC)
        parsing_run.status = ParserRunStatus.SKIPPED.value
        parsing_run.error_message = "Parser produced no records."
        session.commit()
        return _summary(entry, parsing_run)

    evidence_created = 0
    review_items_created = 0
    provider_row = _ensure_provider(session, entry)
    _ensure_cloud_partition(session, provider_row, entry)
    category = _ensure_category(session, entry.product_code)
    product_row = _ensure_product(session, entry, provider_row, category, records)
    _ensure_spec_definitions(session, category, entry)

    for record in records:
        for candidate in record.fields:
            evidence, created = get_or_create_evidence(
                session,
                source_document_id=source_document.id,
                snapshot_record_id=snapshot_record.id if snapshot_record else None,
                content_hash=manifest.content_sha256,
                page_title=document.title,
                candidate=candidate,
            )
            evidence_created += int(created)
            target_identity = _persist_candidate_target(
                session,
                entry,
                product_row,
                record,
                candidate,
                evidence.id,
            )
            field_candidate = _record_field_candidate(
                session,
                parsing_run.id,
                source_document.id,
                snapshot_record.id if snapshot_record else None,
                evidence.id,
                candidate,
                target_identity,
            )
            if candidate.review_status == ReviewStatus.PENDING_REVIEW.value:
                review_items_created += int(
                    _create_review_item(
                        session,
                        entry,
                        parsing_run.id,
                        field_candidate.id,
                        evidence.id,
                        candidate,
                    )
                )

    parsing_run.completed_at = datetime.now(UTC)
    parsing_run.status = (
        ParserRunStatus.PARTIAL.value if review_items_created else ParserRunStatus.SUCCEEDED.value
    )
    parsing_run.records_found = len(records)
    parsing_run.fields_found = sum(len(record.fields) for record in records)
    parsing_run.evidence_created = evidence_created
    parsing_run.review_items_created = review_items_created
    session.commit()
    return _summary(entry, parsing_run)


def _parse_records(
    entry: SourceRegistryEntry,
    document: Any,
    snapshot_id: str,
) -> list[ParsedRecord]:
    if entry.provider_code == HUAWEI_CLOUD_PROVIDER_CODE and entry.product_code == "ecs":
        return parse_ecs_document(document, source_id=entry.source_id, snapshot_id=snapshot_id)
    if entry.provider_code == HUAWEI_CLOUD_PROVIDER_CODE and entry.product_code == "obs":
        return parse_obs_document(document, source_id=entry.source_id, snapshot_id=snapshot_id)
    if entry.provider_code == AWS_PROVIDER_CODE and entry.product_code == "ec2":
        return parse_ec2_document(document, source_id=entry.source_id, snapshot_id=snapshot_id)
    if entry.provider_code == AWS_PROVIDER_CODE and entry.product_code == "s3":
        return parse_s3_document(document, source_id=entry.source_id, snapshot_id=snapshot_id)
    if entry.provider_code == ALIYUN_PROVIDER_CODE and entry.product_code == "ecs":
        return parse_aliyun_ecs_document(
            document,
            source_id=entry.source_id,
            snapshot_id=snapshot_id,
        )
    if entry.provider_code == ALIYUN_PROVIDER_CODE and entry.product_code == "oss":
        return parse_aliyun_oss_document(
            document,
            source_id=entry.source_id,
            snapshot_id=snapshot_id,
        )
    return []


def _parser_name(entry: SourceRegistryEntry) -> str:
    return f"{entry.provider_code}_{entry.product_code or 'unknown'}_html"


def _parser_version(entry: SourceRegistryEntry) -> str:
    if entry.provider_code == ALIYUN_PROVIDER_CODE:
        return aliyun_parser_version_for_product(entry.product_code)
    if entry.provider_code == AWS_PROVIDER_CODE:
        return AWS_PARSER_VERSION
    return HUAWEI_PARSER_VERSION


def _ensure_provider(session: Session, entry: SourceRegistryEntry) -> Provider:
    provider = session.scalar(select(Provider).where(Provider.code == entry.provider_code))
    profile = _provider_profile(entry.provider_code)
    if provider is not None:
        provider.name = profile["name"]
        provider.display_name = profile["display_name"]
        provider.provider_type = profile["provider_type"]
        provider.official_website = provider.official_website or profile["official_website"]
        provider.is_active = True
        session.flush()
        return provider
    provider = Provider(
        code=entry.provider_code,
        name=profile["name"],
        display_name=profile["display_name"],
        provider_type=profile["provider_type"],
        official_website=profile["official_website"],
        is_active=True,
    )
    session.add(provider)
    session.flush()
    return provider


def _provider_profile(provider_code: str) -> dict[str, str]:
    if provider_code == ALIYUN_PROVIDER_CODE:
        return ALIYUN_PROVIDER_PROFILE
    if provider_code == AWS_PROVIDER_CODE:
        return AWS_PROVIDER_PROFILE
    if provider_code == HUAWEI_CLOUD_PROVIDER_CODE:
        return {
            "code": HUAWEI_CLOUD_PROVIDER_CODE,
            "name": "Huawei Cloud Domestic",
            "display_name": "Huawei Cloud",
            "provider_type": "cloud",
            "official_website": "https://www.huaweicloud.com/",
        }
    return {
        "code": provider_code,
        "name": f"Registry provider {provider_code}",
        "display_name": provider_code,
        "provider_type": "registry",
        "official_website": "",
    }


def _ensure_cloud_partition(
    session: Session,
    provider: Provider,
    entry: SourceRegistryEntry,
) -> CloudPartition | None:
    partition_code = entry.cloud_partition
    if partition_code is None and entry.provider_code == AWS_PROVIDER_CODE:
        partition_code = AWS_COMMERCIAL_PARTITION
    if not partition_code:
        return None
    partition = session.scalar(
        select(CloudPartition).where(
            CloudPartition.provider_id == provider.id,
            CloudPartition.partition_code == partition_code,
        )
    )
    profile = _partition_profile(entry.provider_code, partition_code, entry.market_mode)
    if partition is not None:
        partition.partition_name = profile["partition_name"]
        partition.market_mode = profile["market_mode"]
        partition.geography_scope = profile["geography_scope"]
        partition.is_active = True
        session.flush()
        return partition
    partition = CloudPartition(
        provider_id=provider.id,
        partition_code=partition_code,
        partition_name=profile["partition_name"],
        market_mode=profile["market_mode"],
        geography_scope=profile["geography_scope"],
        is_active=True,
    )
    session.add(partition)
    session.flush()
    return partition


def _partition_profile(
    provider_code: str,
    partition_code: str,
    market_mode: object,
) -> dict[str, str]:
    if provider_code == ALIYUN_PROVIDER_CODE and partition_code == ALIYUN_PUBLIC_CN_PARTITION:
        return ALIYUN_PUBLIC_CN_PARTITION_PROFILE
    if provider_code == AWS_PROVIDER_CODE and partition_code == AWS_COMMERCIAL_PARTITION:
        return AWS_COMMERCIAL_PARTITION_PROFILE
    return {
        "partition_code": partition_code,
        "partition_name": partition_code,
        "market_mode": str(market_mode),
        "geography_scope": "",
    }


def _ensure_category(session: Session, product_code: str | None) -> ProductCategory:
    code = "object_storage" if product_code in {"obs", "s3", "oss"} else "compute"
    name = "Object Storage" if product_code in {"obs", "s3", "oss"} else "Compute"
    category = session.scalar(select(ProductCategory).where(ProductCategory.code == code))
    if category is not None:
        return category
    category = ProductCategory(code=code, name=name, description=f"{name} category.")
    session.add(category)
    session.flush()
    return category


def _ensure_product(
    session: Session,
    entry: SourceRegistryEntry,
    provider: Provider,
    category: ProductCategory,
    records: list[ParsedRecord],
) -> Product:
    product_code = entry.product_code or "unknown_product"
    product = session.scalar(
        select(Product).where(Product.provider_id == provider.id, Product.code == product_code)
    )
    field_values = _product_field_values(records, product_code)
    official_name = (
        _canonical_product_name(product_code, entry.provider_code)
        or field_values.get("product.official_name")
        or entry.title
    )
    description = field_values.get("product.description")
    if product is None:
        product = Product(
            provider_id=provider.id,
            category_id=category.id,
            market_mode=str(entry.market_mode),
            code=product_code,
            official_name=official_name,
            display_name=official_name,
            description=description,
            product_status=ProductStatus.UNKNOWN.value,
            official_url=entry.url if entry.source_type == SourceType.PRODUCT_PAGE.value else None,
            documentation_url=entry.url
            if entry.source_type != SourceType.PRODUCT_PAGE.value
            else None,
            first_seen_at=datetime.now(UTC),
            last_verified_at=datetime.now(UTC),
        )
        session.add(product)
        session.flush()
        return product
    if official_name and product.official_name != official_name:
        product.official_name = official_name
        product.display_name = official_name
    if description and not product.description:
        product.description = description
    is_primary_product_page = entry.source_id.endswith("_product_page")
    if entry.source_type == SourceType.PRODUCT_PAGE.value and (
        is_primary_product_page or not product.official_url
    ):
        product.official_url = entry.url
    if entry.source_type != SourceType.PRODUCT_PAGE.value and not product.documentation_url:
        product.documentation_url = entry.url
    product.last_verified_at = datetime.now(UTC)
    session.flush()
    return product


def _canonical_product_name(product_code: str, provider_code: str | None = None) -> str | None:
    if provider_code == ALIYUN_PROVIDER_CODE and product_code == "ecs":
        return "云服务器 ECS"
    if provider_code == ALIYUN_PROVIDER_CODE and product_code == "oss":
        return "对象存储 OSS"
    if product_code == "ec2":
        return "Amazon Elastic Compute Cloud (Amazon EC2)"
    if product_code == "s3":
        return "Amazon Simple Storage Service (Amazon S3)"
    if product_code == "ecs":
        return "弹性云服务器 ECS"
    if product_code == "obs":
        return "对象存储服务 OBS"
    return None


def _product_field_values(records: list[ParsedRecord], product_code: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for record in records:
        if record.record_type != "product" or record.target_identity != product_code:
            continue
        for field in record.fields:
            if field.raw_value is not None:
                values[field.field_code] = str(field.raw_value)
    return values


def _ensure_spec_definitions(
    session: Session,
    category: ProductCategory,
    entry: SourceRegistryEntry,
) -> None:
    mappings = _spec_definitions_for_product(entry.provider_code, entry.product_code)
    for code, (name, data_type, unit) in mappings.items():
        existing = session.scalar(
            select(SpecificationDefinition).where(SpecificationDefinition.code == code)
        )
        if existing is not None:
            continue
        definition = SpecificationDefinition(
            code=code,
            name=name,
            category_id=category.id,
            data_type=data_type,
            canonical_unit=unit,
            is_required=False,
        )
        session.add(definition)
    session.flush()


def _spec_definitions_for_product(
    provider_code: str,
    product_code: str | None,
) -> dict[str, tuple[str, str, str | None]]:
    if provider_code == ALIYUN_PROVIDER_CODE and product_code == "ecs":
        return ALIYUN_ECS_SPEC_DEFINITIONS
    if provider_code == ALIYUN_PROVIDER_CODE and product_code == "oss":
        return ALIYUN_OSS_SPEC_DEFINITIONS
    if product_code == "obs":
        return OBS_SPEC_DEFINITIONS
    if product_code == "ec2":
        return EC2_SPEC_DEFINITIONS
    if product_code == "s3":
        return S3_SPEC_DEFINITIONS
    return ECS_SPEC_DEFINITIONS


def _persist_candidate_target(
    session: Session,
    entry: SourceRegistryEntry,
    product: Product,
    record: ParsedRecord,
    candidate: FieldCandidate,
    evidence_id: int,
) -> str:
    if record.record_type in {"ecs_sku", "aliyun_ecs_sku"}:
        sku = _ensure_sku(session, product, record.target_identity)
        _ensure_family_for_sku(session, entry, product, sku, evidence_id)
        _apply_sku_candidate(sku, candidate)
        _persist_product_specification(session, product, sku.id, candidate, evidence_id)
        return f"sku:{sku.provider_sku_code}"
    if record.record_type == "ec2_sku":
        sku = _ensure_sku(session, product, record.target_identity)
        _ensure_family_for_sku(session, entry, product, sku, evidence_id)
        _apply_sku_candidate(sku, candidate)
        _persist_product_specification(session, product, sku.id, candidate, evidence_id)
        return f"sku:{sku.provider_sku_code}"
    if record.record_type in {"ecs_instance_family", "aliyun_ecs_instance_family"}:
        family = _ensure_product_family(session, entry, product, record, candidate, evidence_id)
        return f"product_family:{family.family_code}"
    if record.record_type == "ec2_instance_family":
        family = _ensure_product_family(session, entry, product, record, candidate, evidence_id)
        return f"product_family:{family.family_code}"
    if record.record_type in {"obs_storage_class", "aliyun_oss_storage_class"}:
        service_tier = _ensure_service_tier(session, product, record, candidate, evidence_id)
        _persist_product_specification(session, product, None, candidate, evidence_id)
        return f"service_tier:{service_tier.tier_code}"
    if record.record_type == "s3_storage_class":
        service_tier = _ensure_service_tier(session, product, record, candidate, evidence_id)
        _persist_product_specification(session, product, None, candidate, evidence_id)
        return f"service_tier:{service_tier.tier_code}"
    if record.record_type == "product_sla":
        sla = _ensure_product_sla(session, product, record, candidate, evidence_id)
        return f"product_sla:{sla.scope}"
    if record.record_type == "region_availability":
        availability = _ensure_region_availability(
            session,
            entry,
            product,
            record,
            candidate,
            evidence_id,
        )
        return f"availability:{availability.region.code}:{availability.target_type}:{availability.target_code}"
    if record.record_type == "zone_availability":
        zone_availability = _ensure_zone_availability(
            session,
            entry,
            product,
            record,
            candidate,
            evidence_id,
        )
        return (
            f"zone_availability:{zone_availability.availability_zone.zone_code}:"
            f"{zone_availability.target_type}:{zone_availability.target_code}"
        )
    if candidate.target_table == "product_specification":
        _persist_product_specification(session, product, None, candidate, evidence_id)
    return f"product:{entry.product_code or product.code}"


def _ensure_sku(session: Session, product: Product, provider_sku_code: str) -> SKU:
    sku = session.scalar(
        select(SKU).where(
            SKU.product_id == product.id,
            SKU.provider_sku_code == provider_sku_code,
        )
    )
    if sku is not None:
        return sku
    sku = SKU(
        product_id=product.id,
        provider_sku_code=provider_sku_code,
        name=provider_sku_code,
        sku_family=infer_ecs_family_code(provider_sku_code),
        status=SKUStatus.UNKNOWN.value,
    )
    session.add(sku)
    session.flush()
    return sku


def _ensure_family_for_sku(
    session: Session,
    entry: SourceRegistryEntry,
    product: Product,
    sku: SKU,
    evidence_id: int,
) -> ProductFamily:
    family_code = sku.sku_family or infer_ecs_family_code(sku.provider_sku_code)
    existing = session.scalar(
        select(ProductFamily).where(
            ProductFamily.product_id == product.id,
            ProductFamily.family_code == family_code,
        )
    )
    if existing is not None:
        return existing
    family = ProductFamily(
        product_id=product.id,
        family_code=family_code,
        family_name=family_code,
        family_type=_family_type_for_product(entry, product.code),
        status=SKUStatus.UNKNOWN.value,
        evidence_id=evidence_id,
        review_status=ReviewStatus.PENDING_REVIEW.value,
    )
    session.add(family)
    session.flush()
    return family


def _ensure_product_family(
    session: Session,
    entry: SourceRegistryEntry,
    product: Product,
    record: ParsedRecord,
    candidate: FieldCandidate,
    evidence_id: int,
) -> ProductFamily:
    family_code = str(candidate.normalized_value or record.target_identity)
    family = session.scalar(
        select(ProductFamily).where(
            ProductFamily.product_id == product.id,
            ProductFamily.family_code == family_code,
        )
    )
    if family is not None:
        if candidate.field_code == "compute.cpu_architecture" and candidate.normalized_value:
            family.architecture = str(candidate.normalized_value)
        if candidate.field_code == "compute.processor_vendor" and candidate.normalized_value:
            family.processor_vendor = str(candidate.normalized_value)
        if candidate.field_code == "compute.processor_model" and candidate.raw_value:
            family.processor_model_raw = str(candidate.raw_value)
        session.flush()
        return family
    family = ProductFamily(
        product_id=product.id,
        family_code=family_code,
        family_name=str(candidate.raw_value or family_code),
        family_type=_family_type_for_product(entry, product.code),
        architecture=str(candidate.normalized_value)
        if candidate.field_code == "compute.cpu_architecture"
        else None,
        processor_vendor=str(candidate.normalized_value)
        if candidate.field_code == "compute.processor_vendor"
        else None,
        processor_model_raw=str(candidate.raw_value)
        if candidate.field_code == "compute.processor_model"
        else None,
        status=SKUStatus.UNKNOWN.value,
        evidence_id=evidence_id,
        review_status=candidate.review_status,
    )
    session.add(family)
    session.flush()
    return family


def _family_type_for_product(entry: SourceRegistryEntry, product_code: str) -> str:
    if entry.provider_code == ALIYUN_PROVIDER_CODE and product_code == "ecs":
        return ProductFamilyType.ALIYUN_ECS_INSTANCE_FAMILY.value
    if entry.provider_code == ALIYUN_PROVIDER_CODE and product_code == "oss":
        return ProductFamilyType.ALIYUN_OSS_STORAGE_CLASS.value
    if entry.provider_code == AWS_PROVIDER_CODE and product_code == "ec2":
        return ProductFamilyType.AWS_EC2_INSTANCE_FAMILY.value
    if entry.provider_code == AWS_PROVIDER_CODE and product_code == "s3":
        return ProductFamilyType.AWS_S3_STORAGE_CLASS.value
    if product_code == "obs":
        return ProductFamilyType.OBS_STORAGE_CLASS.value
    return ProductFamilyType.ECS_INSTANCE_FAMILY.value


def _apply_sku_candidate(sku: SKU, candidate: FieldCandidate) -> None:
    if candidate.field_code == "compute.cpu_architecture" and candidate.normalized_value:
        sku.architecture = str(candidate.normalized_value)


def _ensure_service_tier(
    session: Session,
    product: Product,
    record: ParsedRecord,
    candidate: FieldCandidate,
    evidence_id: int,
) -> ServiceTier:
    tier_code = record.target_identity or normalize_storage_class_code(str(candidate.raw_value))
    service_tier = session.scalar(
        select(ServiceTier).where(
            ServiceTier.product_id == product.id,
            ServiceTier.tier_code == tier_code,
        )
    )
    if service_tier is not None:
        _apply_service_tier_candidate(service_tier, candidate, evidence_id)
        session.flush()
        return service_tier
    service_tier = ServiceTier(
        product_id=product.id,
        tier_code=tier_code,
        official_name=tier_code,
        access_pattern=candidate.excerpt,
        status=SKUStatus.UNKNOWN.value,
        evidence_id=evidence_id,
        review_status=candidate.review_status,
    )
    _apply_service_tier_candidate(service_tier, candidate, evidence_id)
    session.add(service_tier)
    session.flush()
    return service_tier


def _apply_service_tier_candidate(
    service_tier: ServiceTier,
    candidate: FieldCandidate,
    evidence_id: int,
) -> None:
    if candidate.field_code in {
        "obs.storage_class.official_name",
        "s3.storage_class.official_name",
        "oss.storage_class.official_name",
    }:
        service_tier.official_name = str(candidate.raw_value or service_tier.tier_code)
    elif candidate.field_code == "object_storage.minimum_storage_duration_days":
        service_tier.minimum_storage_duration_days = _normalized_int(candidate.normalized_value)
    elif candidate.field_code == "object_storage.retrieval_time_description":
        service_tier.retrieval_characteristics = (
            None if candidate.raw_value is None else str(candidate.raw_value)
        )
    elif candidate.field_code == "object_storage.durability_percentage":
        service_tier.durability_design = (
            None if candidate.raw_value is None else str(candidate.raw_value)
        )
    elif candidate.field_code == "object_storage.availability_percentage":
        service_tier.availability_design = (
            None if candidate.raw_value is None else str(candidate.raw_value)
        )
    if service_tier.evidence_id is None:
        service_tier.evidence_id = evidence_id
    if candidate.review_status == ReviewStatus.PENDING_REVIEW.value:
        service_tier.review_status = ReviewStatus.PENDING_REVIEW.value


def _ensure_region_availability(
    session: Session,
    entry: SourceRegistryEntry,
    product: Product,
    record: ParsedRecord,
    candidate: FieldCandidate,
    evidence_id: int,
) -> Availability:
    del candidate
    values = _record_field_values(record)
    provider = session.get(Provider, product.provider_id)
    if provider is None:
        msg = f"Provider row missing for product_id={product.id}"
        raise ValueError(msg)
    partition = _ensure_cloud_partition(session, provider, entry)
    region_code = values.get("region.code") or record.target_identity
    region_name = values.get("region.name") or region_code
    region = session.scalar(
        select(Region).where(
            Region.provider_id == provider.id,
            Region.code == region_code,
        )
    )
    if region is None:
        region = Region(
            provider_id=provider.id,
            cloud_partition_id=partition.id if partition else None,
            code=region_code,
            name=region_name,
            country_code=_infer_region_country_code(region_code, region_name),
            geography=_infer_region_geography(region_code, region_name),
            market_mode=str(entry.market_mode),
            is_active=True,
        )
        session.add(region)
        session.flush()
    else:
        region.name = region_name
        region.cloud_partition_id = partition.id if partition else region.cloud_partition_id
        region.country_code = region.country_code or _infer_region_country_code(
            region_code,
            region_name,
        )
        region.geography = region.geography or _infer_region_geography(region_code, region_name)
        region.market_mode = str(entry.market_mode)
        region.is_active = True
        session.flush()

    target_type = values.get("availability.target_type") or "product"
    target_code = values.get("availability.target_code") or product.code
    status = values.get("availability.status") or AvailabilityStatus.AVAILABLE.value
    availability = session.scalar(
        select(Availability).where(
            Availability.product_id == product.id,
            Availability.region_id == region.id,
            Availability.target_type == target_type,
            Availability.target_code == target_code,
        )
    )
    if availability is None:
        availability = Availability(
            product_id=product.id,
            region_id=region.id,
            cloud_partition_id=partition.id if partition else None,
            target_type=target_type,
            target_code=target_code,
            availability_status=status,
            public_preview=status == AvailabilityStatus.PREVIEW.value,
            generally_available=status == AvailabilityStatus.AVAILABLE.value,
            last_verified_at=datetime.now(UTC),
            evidence_id=evidence_id,
        )
        session.add(availability)
        session.flush()
        return availability
    availability.cloud_partition_id = partition.id if partition else availability.cloud_partition_id
    availability.availability_status = status
    availability.public_preview = status == AvailabilityStatus.PREVIEW.value
    availability.generally_available = status == AvailabilityStatus.AVAILABLE.value
    availability.last_verified_at = datetime.now(UTC)
    if availability.evidence_id is None:
        availability.evidence_id = evidence_id
    session.flush()
    return availability


def _ensure_zone_availability(
    session: Session,
    entry: SourceRegistryEntry,
    product: Product,
    record: ParsedRecord,
    candidate: FieldCandidate,
    evidence_id: int,
) -> ZoneAvailability:
    del candidate
    values = _record_field_values(record)
    provider = session.get(Provider, product.provider_id)
    if provider is None:
        msg = f"Provider row missing for product_id={product.id}"
        raise ValueError(msg)
    partition = _ensure_cloud_partition(session, provider, entry)
    zone_code = values.get("zone.code") or record.target_identity
    region_code = values.get("region.code") or zone_code.rsplit("-", 1)[0]
    region_name = values.get("region.name") or region_code
    zone_name = values.get("zone.name") or zone_code
    region = session.scalar(
        select(Region).where(
            Region.provider_id == provider.id,
            Region.code == region_code,
        )
    )
    if region is None:
        region = Region(
            provider_id=provider.id,
            cloud_partition_id=partition.id if partition else None,
            code=region_code,
            name=region_name,
            country_code=_infer_region_country_code(region_code, region_name),
            geography=_infer_region_geography(region_code, region_name),
            market_mode=str(entry.market_mode),
            is_active=True,
        )
        session.add(region)
        session.flush()
    else:
        region.name = region_name
        region.cloud_partition_id = partition.id if partition else region.cloud_partition_id
        region.country_code = region.country_code or _infer_region_country_code(
            region_code,
            region_name,
        )
        region.geography = region.geography or _infer_region_geography(region_code, region_name)
        region.market_mode = str(entry.market_mode)
        region.is_active = True
        session.flush()

    zone = session.scalar(
        select(AvailabilityZone).where(
            AvailabilityZone.provider_id == provider.id,
            AvailabilityZone.zone_code == zone_code,
        )
    )
    if zone is None:
        zone = AvailabilityZone(
            provider_id=provider.id,
            region_id=region.id,
            cloud_partition_id=partition.id if partition else None,
            zone_code=zone_code,
            zone_name=zone_name,
            market_mode=str(entry.market_mode),
            is_active=True,
            evidence_id=evidence_id,
        )
        session.add(zone)
        session.flush()
    else:
        zone.region_id = region.id
        zone.cloud_partition_id = partition.id if partition else zone.cloud_partition_id
        zone.zone_name = zone_name
        zone.market_mode = str(entry.market_mode)
        zone.is_active = True
        if zone.evidence_id is None:
            zone.evidence_id = evidence_id
        session.flush()

    target_type = values.get("availability.target_type") or "product"
    target_code = values.get("availability.target_code") or product.code
    status = values.get("availability.status") or AvailabilityStatus.AVAILABLE.value
    zone_availability = session.scalar(
        select(ZoneAvailability).where(
            ZoneAvailability.product_id == product.id,
            ZoneAvailability.availability_zone_id == zone.id,
            ZoneAvailability.target_type == target_type,
            ZoneAvailability.target_code == target_code,
        )
    )
    if zone_availability is None:
        zone_availability = ZoneAvailability(
            product_id=product.id,
            region_id=region.id,
            availability_zone_id=zone.id,
            cloud_partition_id=partition.id if partition else None,
            target_type=target_type,
            target_code=target_code,
            availability_status=status,
            public_preview=status == AvailabilityStatus.PREVIEW.value,
            generally_available=status == AvailabilityStatus.AVAILABLE.value,
            last_verified_at=datetime.now(UTC),
            evidence_id=evidence_id,
        )
        session.add(zone_availability)
        session.flush()
        return zone_availability
    zone_availability.region_id = region.id
    zone_availability.cloud_partition_id = (
        partition.id if partition else zone_availability.cloud_partition_id
    )
    zone_availability.availability_status = status
    zone_availability.public_preview = status == AvailabilityStatus.PREVIEW.value
    zone_availability.generally_available = status == AvailabilityStatus.AVAILABLE.value
    zone_availability.last_verified_at = datetime.now(UTC)
    if zone_availability.evidence_id is None:
        zone_availability.evidence_id = evidence_id
    session.flush()
    return zone_availability


def _record_field_values(record: ParsedRecord) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in record.fields:
        value = field.normalized_value if field.normalized_value is not None else field.raw_value
        if value is not None:
            values[field.field_code] = str(value)
    return values


def _infer_region_country_code(region_code: str, region_name: str) -> str:
    if region_code == "cn-hongkong":
        return "HK"
    if region_code.startswith("cn-"):
        return "CN"
    exact = {
        "af-south-1": "ZA",
        "ap-east-1": "HK",
        "ap-south-1": "IN",
        "ap-south-2": "IN",
        "ap-southeast-1": "SG",
        "ap-southeast-2": "AU",
        "ap-southeast-3": "ID",
        "ap-southeast-4": "AU",
        "ap-southeast-5": "MY",
        "ap-southeast-7": "TH",
        "ap-northeast-1": "JP",
        "ap-northeast-2": "KR",
        "ap-northeast-3": "JP",
        "ca-central-1": "CA",
        "ca-west-1": "CA",
        "eu-central-1": "DE",
        "eu-central-2": "CH",
        "eu-west-1": "IE",
        "eu-west-2": "GB",
        "eu-west-3": "FR",
        "eu-south-1": "IT",
        "eu-south-2": "ES",
        "eu-north-1": "SE",
        "il-central-1": "IL",
        "me-central-1": "AE",
        "me-south-1": "BH",
        "mx-central-1": "MX",
        "sa-east-1": "BR",
    }
    if region_code in exact:
        return exact[region_code]
    if region_code.startswith("us-"):
        return "US"
    lowered = region_name.lower()
    for keyword, country_code in (
        ("united states", "US"),
        ("canada", "CA"),
        ("ireland", "IE"),
        ("london", "GB"),
        ("paris", "FR"),
        ("frankfurt", "DE"),
        ("milan", "IT"),
        ("spain", "ES"),
        ("stockholm", "SE"),
        ("switzerland", "CH"),
        ("tokyo", "JP"),
        ("osaka", "JP"),
        ("seoul", "KR"),
        ("singapore", "SG"),
        ("sydney", "AU"),
        ("melbourne", "AU"),
        ("mumbai", "IN"),
        ("hyderabad", "IN"),
        ("hong kong", "HK"),
        ("jakarta", "ID"),
        ("malaysia", "MY"),
        ("thailand", "TH"),
        ("bahrain", "BH"),
        ("uae", "AE"),
        ("tel aviv", "IL"),
        ("sao paulo", "BR"),
        ("mexico", "MX"),
        ("cape town", "ZA"),
    ):
        if keyword in lowered:
            return country_code
    return "ZZ"


def _infer_region_geography(region_code: str, region_name: str) -> str:
    if region_name:
        return region_name.split("(", 1)[0].strip() or region_name
    if region_code.startswith(("us-", "ca-", "mx-")):
        return "North America"
    if region_code.startswith("eu-"):
        return "Europe"
    if region_code.startswith("ap-"):
        return "Asia Pacific"
    if region_code.startswith("me-") or region_code.startswith("il-"):
        return "Middle East"
    if region_code.startswith("af-"):
        return "Africa"
    if region_code.startswith("sa-"):
        return "South America"
    return "unknown"


def _normalized_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(Decimal(str(value)))
    except (ArithmeticError, ValueError):
        return None


def _ensure_product_sla(
    session: Session,
    product: Product,
    record: ParsedRecord,
    candidate: FieldCandidate,
    evidence_id: int,
) -> ProductSLA:
    scope = record.target_identity or candidate.target_identity or "product"
    raw_value = str(candidate.raw_value)
    existing = session.scalar(
        select(ProductSLA).where(
            ProductSLA.product_id == product.id,
            ProductSLA.record_type == SLARecordType.AVAILABILITY.value,
            ProductSLA.scope == scope,
            ProductSLA.raw_value == raw_value,
            ProductSLA.evidence_id == evidence_id,
        )
    )
    if existing is not None:
        return existing
    normalized_percentage = (
        None if candidate.normalized_value is None else Decimal(str(candidate.normalized_value))
    )
    sla = ProductSLA(
        product_id=product.id,
        record_type=SLARecordType.AVAILABILITY.value,
        metric_name=candidate.field_code,
        scope=scope,
        raw_value=raw_value,
        normalized_percentage=normalized_percentage,
        effective_notes=candidate.excerpt,
        evidence_id=evidence_id,
        review_status=candidate.review_status,
    )
    session.add(sla)
    session.flush()
    return sla


def _persist_product_specification(
    session: Session,
    product: Product,
    sku_id: int | None,
    candidate: FieldCandidate,
    evidence_id: int,
) -> None:
    if not any(candidate.field_code in definitions for definitions in PRODUCT_SPEC_DEFINITION_SETS):
        return
    definition = session.scalar(
        select(SpecificationDefinition).where(SpecificationDefinition.code == candidate.field_code)
    )
    if definition is None:
        return
    statement = select(ProductSpecification).where(
        ProductSpecification.product_id == product.id,
        ProductSpecification.definition_id == definition.id,
        ProductSpecification.raw_value == str(candidate.raw_value),
        ProductSpecification.evidence_id == evidence_id,
    )
    statement = (
        statement.where(ProductSpecification.sku_id.is_(None))
        if sku_id is None
        else statement.where(ProductSpecification.sku_id == sku_id)
    )
    if session.scalar(statement) is not None:
        return
    numeric_value, text_value, boolean_value = _spec_values(candidate)
    specification = ProductSpecification(
        product_id=product.id,
        sku_id=sku_id,
        definition_id=definition.id,
        numeric_value=numeric_value,
        text_value=text_value,
        boolean_value=boolean_value,
        raw_value=str(candidate.raw_value),
        raw_unit=candidate.raw_unit,
        canonical_value=None
        if candidate.normalized_value is None
        else str(candidate.normalized_value),
        canonical_unit=candidate.canonical_unit,
        evidence_id=evidence_id,
        last_verified_at=datetime.now(UTC),
    )
    session.add(specification)
    session.flush()


def _spec_values(candidate: FieldCandidate) -> tuple[Decimal | None, str | None, bool | None]:
    value = (
        candidate.normalized_value
        if candidate.normalized_value is not None
        else candidate.raw_value
    )
    if isinstance(value, bool):
        return None, None, value
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)), None, None
    return None, None if value is None else str(value), None


def _record_field_candidate(
    session: Session,
    parsing_run_id: int,
    source_document_id: int,
    snapshot_record_id: int | None,
    evidence_id: int,
    candidate: FieldCandidate,
    target_identity: str,
) -> ParsedFieldCandidate:
    value_hash = field_value_hash(
        candidate.field_code,
        str(candidate.raw_value),
        str(candidate.normalized_value),
        candidate.locator,
    )
    existing = session.scalar(
        select(ParsedFieldCandidate).where(
            ParsedFieldCandidate.parsing_run_id == parsing_run_id,
            ParsedFieldCandidate.field_code == candidate.field_code,
            ParsedFieldCandidate.target_table == candidate.target_table,
            ParsedFieldCandidate.target_identity == target_identity,
            ParsedFieldCandidate.value_hash == value_hash,
        )
    )
    if existing is not None:
        return existing
    field_candidate = ParsedFieldCandidate(
        parsing_run_id=parsing_run_id,
        source_document_id=source_document_id,
        snapshot_record_id=snapshot_record_id,
        evidence_id=evidence_id,
        target_table=candidate.target_table,
        target_identity=target_identity,
        field_code=candidate.field_code,
        raw_value=None if candidate.raw_value is None else str(candidate.raw_value),
        raw_unit=candidate.raw_unit,
        normalized_value=None
        if candidate.normalized_value is None
        else str(candidate.normalized_value),
        canonical_unit=candidate.canonical_unit,
        locator=candidate.locator,
        excerpt=candidate.excerpt,
        confidence=candidate.confidence,
        review_status=candidate.review_status,
        parser_rule=candidate.parser_rule,
        value_hash=value_hash,
    )
    session.add(field_candidate)
    session.flush()
    return field_candidate


def _create_review_item(
    session: Session,
    entry: SourceRegistryEntry,
    parsing_run_id: int,
    parsed_field_candidate_id: int,
    evidence_id: int,
    candidate: FieldCandidate,
) -> bool:
    existing = session.scalar(
        select(ReviewItem).where(
            ReviewItem.provider_code == entry.provider_code,
            ReviewItem.product_code == entry.product_code,
            ReviewItem.field_code == candidate.field_code,
            ReviewItem.evidence_id == evidence_id,
            ReviewItem.raw_value
            == (None if candidate.raw_value is None else str(candidate.raw_value)),
            ReviewItem.status == ReviewItemStatus.OPEN.value,
        )
    )
    if existing is not None:
        return False
    review_item = ReviewItem(
        item_type=ReviewItemType.LOW_CONFIDENCE_FIELD.value,
        severity=QualityIssueSeverity.MEDIUM.value,
        status=ReviewItemStatus.OPEN.value,
        provider_code=entry.provider_code,
        product_code=entry.product_code,
        field_code=candidate.field_code,
        reason="Field was machine parsed below the confidence threshold.",
        raw_value=None if candidate.raw_value is None else str(candidate.raw_value),
        suggested_action="Review locator and official excerpt before using this field.",
        parsing_run_id=parsing_run_id,
        parsed_field_candidate_id=parsed_field_candidate_id,
        evidence_id=evidence_id,
    )
    session.add(review_item)
    session.flush()
    return True


def _summary(entry: SourceRegistryEntry, parsing_run: ParsingRun) -> ParseSummary:
    return ParseSummary(
        source_id=entry.source_id,
        product_code=entry.product_code or "unknown",
        status=parsing_run.status,
        records_found=parsing_run.records_found,
        fields_found=parsing_run.fields_found,
        evidence_created=parsing_run.evidence_created,
        review_items_created=parsing_run.review_items_created,
        parsing_run_id=parsing_run.id,
        error_message=parsing_run.error_message,
    )
