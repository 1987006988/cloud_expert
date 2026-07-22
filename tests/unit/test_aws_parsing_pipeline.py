import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ServiceTier
from cloud_expert.database.models.region import Availability, Region
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.providers.aws.ec2.parser import parse_ec2_document
from cloud_expert.ingestion.providers.aws.s3.parser import parse_s3_document
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.parsing.html_adapter import load_html_document
from cloud_expert.parsing.pipeline import parse_source_entry
from cloud_expert.quality.partitions import count_partition_region_violations

FIXTURE_DIR = Path("tests/fixtures")


def _raw_dir(name: str) -> Path:
    path = Path("test_outputs") / f"{name}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _aws_fixture_entry(
    fixture_path: Path,
    *,
    source_id: str,
    product_code: str,
    source_type: str = "specification",
) -> SourceRegistryEntry:
    return SourceRegistryEntry.model_validate(
        {
            "source_id": source_id,
            "provider_code": "aws",
            "market_mode": "international",
            "cloud_partition": "aws",
            "product_code": product_code,
            "source_type": source_type,
            "title": f"{source_id} fixture",
            "url": f"https://example.invalid/{source_id}",
            "language": "en-US",
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


def test_aws_ec2_parser_extracts_sku_specs_and_filters_partition_regions() -> None:
    specs = parse_ec2_document(
        load_html_document(FIXTURE_DIR / "aws_ec2_specs_fixture.html"),
        source_id="aws_ec2_general_purpose_specs",
        snapshot_id="snapshot-1",
    )
    sku_records = [record for record in specs if record.record_type == "ec2_sku"]
    field_codes = {field.field_code for record in sku_records for field in record.fields}

    assert len(sku_records) == 2
    assert {
        "sku.provider_sku_code",
        "compute.vcpu_count",
        "compute.memory_gib",
        "compute.processor_model",
        "compute.cpu_architecture",
        "network.baseline_bandwidth_gbps",
        "network.max_bandwidth_gbps",
    } <= field_codes

    regions = parse_ec2_document(
        load_html_document(FIXTURE_DIR / "aws_ec2_regions_fixture.html"),
        source_id="aws_ec2_regions",
        snapshot_id="snapshot-2",
    )
    region_records = [record for record in regions if record.record_type == "region_availability"]
    assert [record.target_identity for record in region_records] == ["us-east-1"]


def test_aws_s3_parser_extracts_storage_classes_capabilities_and_regions() -> None:
    storage = parse_s3_document(
        load_html_document(FIXTURE_DIR / "aws_s3_storage_fixture.html"),
        source_id="aws_s3_storage_classes",
        snapshot_id="snapshot-1",
    )
    storage_records = [record for record in storage if record.record_type == "s3_storage_class"]
    field_codes = {field.field_code for record in storage_records for field in record.fields}

    assert len(storage_records) == 2
    assert {
        "s3.storage_class.official_name",
        "object_storage.minimum_storage_duration_days",
        "object_storage.durability_percentage",
        "object_storage.availability_percentage",
    } <= field_codes

    regions = parse_s3_document(
        load_html_document(FIXTURE_DIR / "aws_s3_regions_fixture.html"),
        source_id="aws_s3_regions",
        snapshot_id="snapshot-2",
    )
    region_records = [record for record in regions if record.record_type == "region_availability"]
    assert [record.target_identity for record in region_records] == ["us-east-1"]


def test_aws_parse_pipeline_persists_partitioned_ec2_and_s3_data(session: Session) -> None:
    raw_dir = _raw_dir("aws_pipeline")
    store = SnapshotStore(raw_dir)
    entries = [
        _aws_fixture_entry(
            FIXTURE_DIR / "aws_ec2_specs_fixture.html",
            source_id="aws_ec2_general_purpose_specs",
            product_code="ec2",
        ),
        _aws_fixture_entry(
            FIXTURE_DIR / "aws_ec2_regions_fixture.html",
            source_id="aws_ec2_regions",
            product_code="ec2",
            source_type="region_availability",
        ),
        _aws_fixture_entry(
            FIXTURE_DIR / "aws_s3_storage_fixture.html",
            source_id="aws_s3_storage_classes",
            product_code="s3",
        ),
        _aws_fixture_entry(
            FIXTURE_DIR / "aws_s3_regions_fixture.html",
            source_id="aws_s3_regions",
            product_code="s3",
            source_type="region_availability",
        ),
    ]

    for entry in entries:
        outcome = SourceFetcher(snapshot_store=store).fetch(entry, session=session)
        summary = parse_source_entry(session, entry, store)
        assert outcome.status == "succeeded"
        assert summary.status in {"succeeded", "partial"}

    assert session.query(Product).filter(Product.code.in_(("ec2", "s3"))).count() == 2
    assert session.query(CloudPartition).filter_by(partition_code="aws").count() == 1
    assert session.query(SKU).count() == 2
    assert session.query(ProductFamily).count() >= 2
    assert session.query(ServiceTier).count() == 2
    assert session.query(ProductSpecification).count() > 0
    assert session.query(Region).filter_by(code="us-east-1").count() == 1
    assert session.query(Availability).count() == 2
    assert count_partition_region_violations(
        session,
        provider_code="aws",
        partition_code="aws",
    ) == 0
