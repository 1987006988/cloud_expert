import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from cloud_expert.database.models.parsing import ParsingRun
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ProductSLA, ServiceTier
from cloud_expert.database.models.review import ReviewItem
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.providers.huawei_cloud.ecs.parser import parse_ecs_document
from cloud_expert.ingestion.providers.huawei_cloud.obs.parser import parse_obs_document
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.parsing.html_adapter import load_html_document
from cloud_expert.parsing.pipeline import parse_source_entry
from cloud_expert.quality.reports import build_quality_report

FIXTURE_DIR = Path("tests/fixtures")


def _raw_dir(name: str) -> Path:
    path = Path("test_outputs") / f"{name}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fixture_entry(
    fixture_path: Path,
    *,
    source_id: str,
    product_code: str,
    source_type: str = "specification",
) -> SourceRegistryEntry:
    return SourceRegistryEntry.model_validate(
        {
            "source_id": source_id,
            "provider_code": "huawei_cloud",
            "market_mode": "domestic",
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


def test_huawei_ecs_parser_extracts_sku_specs_and_sla() -> None:
    specs_document = load_html_document(FIXTURE_DIR / "huawei_ecs_specs_fixture.html")
    records = parse_ecs_document(
        specs_document,
        source_id="huawei_cloud_ecs_general_entry_specs",
        snapshot_id="snapshot-1",
    )

    sku_records = [record for record in records if record.record_type == "ecs_sku"]
    assert len(sku_records) == 2
    field_codes = {field.field_code for record in sku_records for field in record.fields}
    assert {
        "sku.provider_sku_code",
        "compute.vcpu_count",
        "compute.memory_gib",
        "network.max_bandwidth_gbps",
        "network.max_pps",
        "system.virtualization_type",
    } <= field_codes

    sla_document = load_html_document(FIXTURE_DIR / "huawei_ecs_sla_fixture.html")
    sla_records = parse_ecs_document(
        sla_document,
        source_id="huawei_cloud_ecs_sla",
        snapshot_id="snapshot-2",
    )
    assert [
        record.target_identity for record in sla_records if record.record_type == "product_sla"
    ] == [
        "ecs_single_instance",
        "ecs_multi_az",
    ]


def test_huawei_obs_parser_extracts_storage_classes_capabilities_and_sla() -> None:
    storage_document = load_html_document(FIXTURE_DIR / "huawei_obs_storage_fixture.html")
    records = parse_obs_document(
        storage_document,
        source_id="huawei_cloud_obs_storage_classes",
        snapshot_id="snapshot-1",
    )

    storage_records = [record for record in records if record.record_type == "obs_storage_class"]
    assert len(storage_records) == 4
    field_codes = {field.field_code for record in records for field in record.fields}
    assert {
        "obs.storage_class.official_name",
        "object_storage.minimum_storage_duration_days",
        "object_storage.durability_percentage",
        "object_storage.availability_percentage",
        "object_storage.lifecycle_management_supported",
        "object_storage.cross_region_replication_supported",
        "object_storage.server_side_encryption_supported",
    } <= field_codes

    sla_document = load_html_document(FIXTURE_DIR / "huawei_obs_sla_fixture.html")
    sla_records = parse_obs_document(
        sla_document,
        source_id="huawei_cloud_obs_sla",
        snapshot_id="snapshot-2",
    )
    assert len([record for record in sla_records if record.record_type == "product_sla"]) == 5
    assert not [record for record in sla_records if record.record_type == "obs_storage_class"]


def test_huawei_fetch_parse_pipeline_is_idempotent_for_product_data(
    session: Session,
) -> None:
    raw_dir = _raw_dir("huawei_ecs_pipeline")
    entry = _fixture_entry(
        FIXTURE_DIR / "huawei_ecs_specs_fixture.html",
        source_id="huawei_cloud_ecs_general_entry_specs",
        product_code="ecs",
    )
    store = SnapshotStore(raw_dir)
    outcome = SourceFetcher(snapshot_store=store).fetch(entry, session=session)

    first = parse_source_entry(session, entry, store)
    first_counts = {
        "product": session.query(Product).count(),
        "sku": session.query(SKU).count(),
        "family": session.query(ProductFamily).count(),
        "spec": session.query(ProductSpecification).count(),
        "evidence": session.query(Evidence).count(),
    }
    second = parse_source_entry(session, entry, store)
    second_counts = {
        "product": session.query(Product).count(),
        "sku": session.query(SKU).count(),
        "family": session.query(ProductFamily).count(),
        "spec": session.query(ProductSpecification).count(),
        "evidence": session.query(Evidence).count(),
    }

    assert outcome.status == "succeeded"
    assert first.status in {"succeeded", "partial"}
    assert second.status in {"succeeded", "partial"}
    assert first_counts == second_counts
    assert first_counts["product"] == 1
    assert first_counts["sku"] == 2
    assert first_counts["family"] >= 1
    assert first_counts["spec"] > 0
    assert first_counts["evidence"] > 0
    assert session.query(ParsingRun).count() == 2


def test_huawei_obs_pipeline_creates_review_items_quality_report_and_sla(
    session: Session,
) -> None:
    raw_dir = _raw_dir("huawei_obs_pipeline")
    store = SnapshotStore(raw_dir)
    storage_entry = _fixture_entry(
        FIXTURE_DIR / "huawei_obs_storage_fixture.html",
        source_id="huawei_cloud_obs_storage_classes",
        product_code="obs",
    )
    sla_entry = _fixture_entry(
        FIXTURE_DIR / "huawei_obs_sla_fixture.html",
        source_id="huawei_cloud_obs_sla",
        product_code="obs",
        source_type="sla",
    )

    SourceFetcher(snapshot_store=store).fetch(storage_entry, session=session)
    SourceFetcher(snapshot_store=store).fetch(sla_entry, session=session)
    storage_summary = parse_source_entry(session, storage_entry, store)
    sla_summary = parse_source_entry(session, sla_entry, store)
    report = build_quality_report(session, provider_code="huawei_cloud", product_code="obs")

    assert storage_summary.status == "partial"
    assert sla_summary.status == "succeeded"
    assert session.query(ServiceTier).count() == 4
    assert session.query(ProductSLA).count() == 5
    assert session.query(ReviewItem).count() >= 1
    assert report["service_tier_records"] == 4
    assert report["sla_records"] == 5
    assert report["human_review_completed"] is False


def test_registered_huawei_sources_are_domestic_official_and_non_intl() -> None:
    entries = load_registry_entries(Path("data/source_registry/domestic/huawei_cloud"))
    assert len(entries) == 24
    assert {entry.product_code for entry in entries} == {"ecs", "obs"}
    assert all(entry.provider_code == "huawei_cloud" for entry in entries)
    assert all(str(entry.market_mode) == "domestic" for entry in entries)
    assert all(
        entry.authority_level in {"official_primary", "official_secondary"} for entry in entries
    )
    assert all("/intl/" not in entry.url for entry in entries)
    assert all(entry.requires_authentication is False for entry in entries)
    assert all(entry.allow_automated_fetch is True for entry in entries)
