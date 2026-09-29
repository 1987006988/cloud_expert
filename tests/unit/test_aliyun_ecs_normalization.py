"""Synthetic-only parser/normalization integration in the in-memory test database."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import CanonicalFieldDefinition, NormalizedSpecification
from cloud_expert.database.models.product import SKU
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.providers.aliyun.common import PARSER_VERSION as LEGACY_ALIYUN_VERSION
from cloud_expert.ingestion.providers.aliyun.common import parser_version_for_product
from cloud_expert.ingestion.providers.aliyun.ecs.mappings import ALIYUN_ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aliyun.ecs.parser import PARSER_VERSION as ECS_VERSION
from cloud_expert.ingestion.providers.aliyun.oss.mappings import ALIYUN_OSS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aliyun.oss.parser import parse_oss_document
from cloud_expert.ingestion.providers.aws.ec2.mappings import EC2_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.s3.mappings import S3_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.ecs.mappings import ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.obs.mappings import OBS_SPEC_DEFINITIONS
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.normalization.canonical_fields import (
    legacy_mapping_by_source_field,
    validate_canonical_registry,
)
from cloud_expert.normalization.canonical_service import normalize_specifications
from cloud_expert.parsing.html_adapter import load_html_document
from cloud_expert.parsing.pipeline import parse_source_entry

BASELINE_FIELDS = {
    "storage.cloud_disk_baseline_iops": ("compute.block_storage.iops", "IOPS"),
    "network.cloud_disk_baseline_bandwidth_gbps": ("compute.block_storage.bandwidth_gbps", "Gbps"),
    "network.baseline_pps": ("compute.network.packets_per_second", "PPS"),
    "network.baseline_connections": ("compute.network.connections", "count"),
}
MAXIMUM_FIELDS = {
    "storage.cloud_disk_iops": ("compute.block_storage.iops", "IOPS"),
    "network.cloud_disk_bandwidth_gbps": ("compute.block_storage.bandwidth_gbps", "Gbps"),
    "network.max_pps": ("compute.network.packets_per_second", "PPS"),
    "network.max_connections": ("compute.network.connections", "count"),
}


def test_aliyun_product_version_routing_keeps_ecs_and_oss_separate() -> None:
    assert parser_version_for_product("ecs") == ECS_VERSION
    assert ECS_VERSION == "2026.09.c09_aliyun_ecs_table_units_v2"
    oss_records = parse_oss_document(
        load_html_document(Path("tests/fixtures/aliyun_oss_storage_fixture.html")),
        source_id="synthetic_aliyun_oss_storage_classes",
        snapshot_id="synthetic-version-check",
    )
    assert oss_records
    assert {record.parser_version for record in oss_records} == {
        parser_version_for_product("oss"),
        LEGACY_ALIYUN_VERSION,
    }
    assert parser_version_for_product("oss") == LEGACY_ALIYUN_VERSION != ECS_VERSION


@pytest.mark.parametrize("product_code", [None, "unknown", "ECS", "ec2", "obs"])
def test_aliyun_legacy_version_fallback_is_unchanged(product_code: str | None) -> None:
    assert parser_version_for_product(product_code) == LEGACY_ALIYUN_VERSION


def test_four_baseline_mappings_are_additive_sku_scoped_and_aliyun_registered() -> None:
    assert validate_canonical_registry() == []
    mappings = legacy_mapping_by_source_field()
    for source_code, (canonical_code, unit) in BASELINE_FIELDS.items():
        assert source_code in ALIYUN_ECS_SPEC_DEFINITIONS
        assert ALIYUN_ECS_SPEC_DEFINITIONS[source_code][1:] == ("numeric", unit)
        assert mappings[source_code].canonical_field_code == canonical_code
        assert mappings[source_code].canonical_unit == unit
        assert mappings[source_code].value_qualifier == "baseline"
        assert mappings[source_code].scope_type == "sku"
    for source_code, (canonical_code, unit) in MAXIMUM_FIELDS.items():
        assert mappings[source_code].canonical_field_code == canonical_code
        assert mappings[source_code].canonical_unit == unit
        assert mappings[source_code].value_qualifier == "maximum"
        assert mappings[source_code].scope_type == "sku"
    for definitions in (
        ALIYUN_OSS_SPEC_DEFINITIONS,
        EC2_SPEC_DEFINITIONS,
        S3_SPEC_DEFINITIONS,
        ECS_SPEC_DEFINITIONS,
        OBS_SPEC_DEFINITIONS,
    ):
        assert set(BASELINE_FIELDS).isdisjoint(definitions)


def _synthetic_entry(path: Path) -> SourceRegistryEntry:
    return SourceRegistryEntry.model_validate(
        {
            "source_id": "synthetic_aliyun_ecs_instance_qualifiers",
            "provider_code": "aliyun",
            "market_mode": "domestic",
            "cloud_partition": "aliyun_public_cn",
            "product_code": "ecs",
            "source_type": "specification",
            "title": "Synthetic ECS qualifier fixture, not product evidence",
            "authority_level": "unknown",
            "url": "https://example.invalid/synthetic-ecs-qualifiers",
            "expected_content_type": ["text/html"],
            "domain_policy": {"allowed_domains": ["example.invalid"]},
            "fixture_response_path": str(path.resolve()),
            "fixture_response_content_type": "text/html",
        }
    )


def test_synthetic_baseline_and_maximum_survive_parse_persistence_and_normalization(
    session: Session, tmp_path: Path
) -> None:
    fixture = tmp_path / "synthetic_qualifiers.html"
    fixture.write_text(
        "<html><head><title>Synthetic ECS qualifier fixture</title></head><body>"
        "<h1>Synthetic ECS table, not product evidence</h1>"
        "<table><tr><th>Instance type</th>"
        "<th>云盘 IOPS 基础/突发</th><th>云盘带宽基础/突发（Gbit/s）</th>"
        "<th>网络收发包 PPS 基础/突发</th><th>连接数基础/突发</th></tr>"
        "<tr><td>ecs.synthetic.large</td><td>2 万/最高 8 万</td>"
        "<td>1.25/最高 4</td><td>30 万/最高 90 万</td><td>4 万/最高 12 万</td>"
        "</tr></table></body></html>",
        encoding="utf-8",
    )
    entry = _synthetic_entry(fixture)
    store = SnapshotStore(tmp_path / "synthetic_raw")
    outcome = SourceFetcher(snapshot_store=store).fetch(entry, session=session)
    assert outcome.status == "succeeded"
    parsed = parse_source_entry(session, entry, store)
    assert parsed.status == "succeeded"

    expected_values = {
        "storage.cloud_disk_baseline_iops": Decimal("20000"),
        "storage.cloud_disk_iops": Decimal("80000"),
        "network.cloud_disk_baseline_bandwidth_gbps": Decimal("1.25"),
        "network.cloud_disk_bandwidth_gbps": Decimal("4"),
        "network.baseline_pps": Decimal("300000"),
        "network.max_pps": Decimal("900000"),
        "network.baseline_connections": Decimal("40000"),
        "network.max_connections": Decimal("120000"),
    }
    specs = session.execute(
        select(ProductSpecification, SpecificationDefinition).join(
            SpecificationDefinition,
            ProductSpecification.definition_id == SpecificationDefinition.id,
        )
    ).all()
    assert {definition.code: spec.numeric_value for spec, definition in specs} == expected_values
    sku = session.scalars(select(SKU)).one()
    evidence_ids = {spec.evidence_id for spec, _ in specs}
    assert len(evidence_ids) == 8
    evidence_count = session.scalar(select(func.count()).select_from(Evidence))

    first = normalize_specifications(
        session, provider_code="aliyun", product_code="ecs", run_key="synthetic_qualifiers"
    )
    assert first.records_created == 8
    assert first.records_skipped == 0
    normalized_rows = session.execute(
        select(
            NormalizedSpecification,
            ProductSpecification,
            SpecificationDefinition,
            CanonicalFieldDefinition,
        )
        .join(
            ProductSpecification,
            NormalizedSpecification.product_specification_id == ProductSpecification.id,
        )
        .join(
            SpecificationDefinition,
            ProductSpecification.definition_id == SpecificationDefinition.id,
        )
        .join(
            CanonicalFieldDefinition,
            NormalizedSpecification.canonical_field_id == CanonicalFieldDefinition.id,
        )
    ).all()
    assert len(normalized_rows) == 8
    identities = set()
    for normalized, spec, definition, canonical in normalized_rows:
        qualifier = "baseline" if definition.code in BASELINE_FIELDS else "maximum"
        canonical_code, unit = {**BASELINE_FIELDS, **MAXIMUM_FIELDS}[definition.code]
        assert canonical.code == canonical_code
        assert normalized.value_qualifier == qualifier
        assert normalized.canonical_unit == unit
        assert normalized.numeric_value == expected_values[definition.code]
        assert normalized.scope_type == "sku"
        assert normalized.scope_identity == sku.provider_sku_code == "ecs.synthetic.large"
        assert normalized.sku_id == sku.id
        assert normalized.evidence_id == spec.evidence_id
        assert normalized.raw_value == spec.raw_value
        assert normalized.review_status == "machine_extracted"
        identities.add((canonical.code, normalized.value_qualifier, normalized.scope_identity))
    assert len(identities) == 8

    second = normalize_specifications(
        session, provider_code="aliyun", product_code="ecs", run_key="synthetic_qualifiers"
    )
    assert second.records_created == 0
    assert second.records_updated == 8
    assert session.scalar(select(func.count()).select_from(NormalizedSpecification)) == 8
    assert session.scalar(select(func.count()).select_from(Evidence)) == evidence_count
    source = session.scalars(select(SourceDocument)).one()
    assert source.authority_level == "unknown"
    assert source.url == entry.url
    assert all(
        evidence.review_status == "machine_extracted"
        for evidence in session.scalars(select(Evidence))
    )
