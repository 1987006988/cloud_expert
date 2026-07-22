import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ProductSLA, ServiceTier
from cloud_expert.database.models.region import (
    Availability,
    AvailabilityZone,
    Region,
    ZoneAvailability,
)
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.providers.aliyun.ecs.parser import parse_ecs_document
from cloud_expert.ingestion.providers.aliyun.oss.parser import parse_oss_document
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.parsing.html_adapter import load_html_document
from cloud_expert.parsing.pipeline import parse_source_entry
from cloud_expert.quality.evidence_checks import count_missing_evidence_links
from cloud_expert.quality.partitions import (
    count_partition_region_violations,
    count_partition_zone_violations,
)
from cloud_expert.quality.reports import build_quality_report

FIXTURE_DIR = Path("tests/fixtures")


def _raw_dir(name: str) -> Path:
    path = Path("test_outputs") / f"{name}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _aliyun_fixture_entry(
    fixture_path: Path,
    *,
    source_id: str,
    product_code: str,
    source_type: str = "specification",
) -> SourceRegistryEntry:
    return SourceRegistryEntry.model_validate(
        {
            "source_id": source_id,
            "provider_code": "aliyun",
            "market_mode": "domestic",
            "cloud_partition": "aliyun_public_cn",
            "product_code": product_code,
            "source_type": source_type,
            "title": f"{source_id} fixture",
            "url": f"https://example.invalid/{source_id}",
            "language": "zh-CN",
            "authority_level": "official_primary",
            "expected_content_type": ["text/html"],
            "expected_file_extension": ".html",
            "domain_policy": {
                "allowed_domains": ["example.invalid"],
                "allow_subdomains": False,
                "allow_redirects": True,
                "allowed_redirect_domains": ["example.invalid"],
            },
            "fetch_policy": {
                "timeout_seconds": 10,
                "connect_timeout_seconds": 5,
                "read_timeout_seconds": 10,
                "max_retries": 0,
                "retry_backoff_seconds": 0,
                "min_interval_seconds": 0,
                "max_content_length_bytes": 1048576,
                "user_agent_profile": "test",
            },
            "storage_policy": {
                "keep_all_versions": True,
                "deduplicate_identical_content": True,
                "store_response_headers": True,
                "store_request_headers": False,
                "compression": "none",
                "retention_policy": "keep_all",
            },
            "schedule": {"update_frequency": "manual", "priority": 1},
            "fixture_response_path": str(fixture_path.resolve()),
            "fixture_response_content_type": "text/html",
        }
    )


def test_aliyun_ecs_parser_extracts_skus_families_regions_zones_and_sla() -> None:
    specs = parse_ecs_document(
        load_html_document(FIXTURE_DIR / "aliyun_ecs_specs_fixture.html"),
        source_id="aliyun_ecs_instance_families",
        snapshot_id="snapshot-1",
    )
    sku_records = [record for record in specs if record.record_type == "aliyun_ecs_sku"]
    family_records = [
        record for record in specs if record.record_type == "aliyun_ecs_instance_family"
    ]
    field_codes = {field.field_code for record in sku_records for field in record.fields}

    assert len(sku_records) == 2
    assert {record.target_identity for record in family_records} == {"g8i", "c8y"}
    assert {
        "sku.provider_sku_code",
        "compute.vcpu_count",
        "compute.memory_gib",
        "compute.processor_vendor",
        "compute.cpu_architecture",
        "network.max_bandwidth_gbps",
        "network.max_pps",
        "storage.cloud_disk_iops",
    } <= field_codes

    region_zone_records = parse_ecs_document(
        load_html_document(FIXTURE_DIR / "aliyun_ecs_regions_zones_fixture.html"),
        source_id="aliyun_ecs_regions_zones",
        snapshot_id="snapshot-2",
    )
    assert [
        record.target_identity
        for record in region_zone_records
        if record.record_type == "region_availability"
    ] == ["cn-hangzhou", "cn-beijing"]
    assert [
        record.target_identity
        for record in region_zone_records
        if record.record_type == "zone_availability"
    ] == ["cn-hangzhou-i", "cn-hangzhou-j", "cn-beijing-l"]

    sla_records = parse_ecs_document(
        load_html_document(FIXTURE_DIR / "aliyun_ecs_sla_fixture.html"),
        source_id="aliyun_ecs_sla",
        snapshot_id="snapshot-3",
    )
    assert [
        record.target_identity for record in sla_records if record.record_type == "product_sla"
    ] == ["ecs_single_instance", "ecs_multi_zone"]


def test_aliyun_oss_parser_extracts_storage_classes_regions_and_sla() -> None:
    storage = parse_oss_document(
        load_html_document(FIXTURE_DIR / "aliyun_oss_storage_fixture.html"),
        source_id="aliyun_oss_storage_classes",
        snapshot_id="snapshot-1",
    )
    storage_records = [
        record for record in storage if record.record_type == "aliyun_oss_storage_class"
    ]
    field_codes = {field.field_code for record in storage_records for field in record.fields}

    assert {record.target_identity for record in storage_records} == {
        "standard",
        "infrequent_access",
        "archive",
        "cold_archive",
        "deep_cold_archive",
    }
    assert {
        "oss.storage_class.official_name",
        "object_storage.minimum_storage_duration_days",
        "object_storage.minimum_billable_object_size_kib",
        "object_storage.durability_percentage",
        "object_storage.availability_percentage",
    } <= field_codes

    regions = parse_oss_document(
        load_html_document(FIXTURE_DIR / "aliyun_oss_regions_fixture.html"),
        source_id="aliyun_oss_regions",
        snapshot_id="snapshot-2",
    )
    assert [
        record.target_identity for record in regions if record.record_type == "region_availability"
    ] == ["cn-hangzhou", "cn-beijing"]

    sla_records = parse_oss_document(
        load_html_document(FIXTURE_DIR / "aliyun_oss_sla_fixture.html"),
        source_id="aliyun_oss_sla",
        snapshot_id="snapshot-3",
    )
    assert [
        record.target_identity for record in sla_records if record.record_type == "product_sla"
    ] == ["oss_service_commitment"]


def test_aliyun_pipeline_persists_domestic_ecs_oss_and_zone_data(session: Session) -> None:
    raw_dir = _raw_dir("aliyun_pipeline")
    store = SnapshotStore(raw_dir)
    entries = [
        _aliyun_fixture_entry(
            FIXTURE_DIR / "aliyun_ecs_specs_fixture.html",
            source_id="aliyun_ecs_instance_families",
            product_code="ecs",
        ),
        _aliyun_fixture_entry(
            FIXTURE_DIR / "aliyun_ecs_regions_zones_fixture.html",
            source_id="aliyun_ecs_regions_zones",
            product_code="ecs",
            source_type="region_availability",
        ),
        _aliyun_fixture_entry(
            FIXTURE_DIR / "aliyun_ecs_sla_fixture.html",
            source_id="aliyun_ecs_sla",
            product_code="ecs",
            source_type="sla",
        ),
        _aliyun_fixture_entry(
            FIXTURE_DIR / "aliyun_oss_storage_fixture.html",
            source_id="aliyun_oss_storage_classes",
            product_code="oss",
        ),
        _aliyun_fixture_entry(
            FIXTURE_DIR / "aliyun_oss_regions_fixture.html",
            source_id="aliyun_oss_regions",
            product_code="oss",
            source_type="region_availability",
        ),
        _aliyun_fixture_entry(
            FIXTURE_DIR / "aliyun_oss_sla_fixture.html",
            source_id="aliyun_oss_sla",
            product_code="oss",
            source_type="sla",
        ),
    ]

    for entry in entries:
        outcome = SourceFetcher(snapshot_store=store).fetch(entry, session=session)
        summary = parse_source_entry(session, entry, store)
        assert outcome.status == "succeeded"
        assert summary.status in {"succeeded", "partial"}

    ecs_report = build_quality_report(session, provider_code="aliyun", product_code="ecs")
    oss_report = build_quality_report(session, provider_code="aliyun", product_code="oss")

    assert session.query(Product).filter(Product.code.in_(("ecs", "oss"))).count() == 2
    assert session.query(CloudPartition).filter_by(partition_code="aliyun_public_cn").count() == 1
    assert session.query(SKU).count() == 2
    assert session.query(ProductFamily).count() == 2
    assert session.query(ServiceTier).count() == 5
    assert session.query(ProductSpecification).count() > 0
    assert session.query(Region).filter(Region.code.in_(("cn-hangzhou", "cn-beijing"))).count() == 2
    assert session.query(Availability).count() == 4
    assert session.query(AvailabilityZone).count() == 3
    assert session.query(ZoneAvailability).count() == 3
    assert session.query(ProductSLA).count() == 3
    assert count_missing_evidence_links(session) == 0
    assert (
        count_partition_region_violations(
            session,
            provider_code="aliyun",
            partition_code="aliyun_public_cn",
        )
        == 0
    )
    assert (
        count_partition_zone_violations(
            session,
            provider_code="aliyun",
            partition_code="aliyun_public_cn",
        )
        == 0
    )
    assert ecs_report["zone_records"] == 3
    assert ecs_report["zone_availability_records"] == 3
    assert oss_report["service_tier_records"] == 5
