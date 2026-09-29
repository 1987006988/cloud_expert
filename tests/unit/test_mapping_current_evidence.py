"""Mapping integration with synthetic, in-memory records and temporary raw snapshots."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.config.settings import get_settings
from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import SKU, Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.mapping.pipeline import _numeric_value, _sku_values, _sku_values_for_skus
from cloud_expert.normalization import evidence_validity
from cloud_expert.normalization.canonical_service import normalize_specifications

CPU = "compute.cpu.vcpu_count"
MEMORY = "compute.memory.capacity_gib"


@dataclass
class Catalog:
    raw_root: Path
    product: Product
    sku: SKU
    partition: CloudPartition
    definitions: tuple[SpecificationDefinition, SpecificationDefinition]


@dataclass
class Chain:
    source: SourceDocument
    snapshot: SnapshotRecord
    evidence: Evidence
    raw_path: Path
    rows: dict[str, NormalizedSpecification]


@pytest.fixture
def catalog(session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Catalog:
    root = tmp_path / "synthetic_raw"
    root.mkdir()
    settings = replace(get_settings(), raw_data_dir=str(root))
    monkeypatch.setattr(evidence_validity, "get_settings", lambda: settings)
    provider = Provider(
        code="synthetic_mapping",
        name="Synthetic mapping provider",
        display_name="Synthetic mapping provider",
        provider_type="fixture",
    )
    category = ProductCategory(code="compute", name="Synthetic compute")
    session.add_all([provider, category])
    session.flush()
    product = Product(
        provider_id=provider.id,
        category_id=category.id,
        code="synthetic_compute",
        official_name="Synthetic compute fixture",
        display_name="Synthetic compute fixture",
        market_mode="domestic",
        product_status="unknown",
    )
    partition = CloudPartition(
        provider_id=provider.id,
        partition_code="synthetic_partition",
        partition_name="Synthetic partition",
        market_mode=product.market_mode,
        is_active=True,
    )
    definitions = (
        SpecificationDefinition(
            code="compute.vcpu_count",
            name="Synthetic CPU count",
            category_id=category.id,
            data_type="numeric",
            canonical_unit="count",
        ),
        SpecificationDefinition(
            code="compute.memory_gib",
            name="Synthetic memory capacity",
            category_id=category.id,
            data_type="numeric",
            canonical_unit="GiB",
        ),
    )
    session.add_all([product, partition, *definitions])
    session.flush()
    sku = SKU(
        product_id=product.id,
        provider_sku_code="synthetic.compute.large",
        name="Synthetic compute SKU",
        status="unknown",
    )
    session.add(sku)
    session.flush()
    return Catalog(root, product, sku, partition, definitions)


def _chain(session: Session, catalog: Catalog, label: str, cpu: int, memory: int) -> Chain:
    excerpt = f"Synthetic-only {label}: CPU {cpu} count; memory {memory} GiB. Not a cloud fact."
    raw = f'<html><body><p id="synthetic">{excerpt}</p></body></html>'.encode()
    path = catalog.raw_root / f"{label}.html"
    path.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    captured_at = datetime(2026, 9, 30, tzinfo=UTC)
    source = SourceDocument(
        provider_id=catalog.product.provider_id,
        source_type="specification",
        title=f"Synthetic {label} source",
        url=f"https://example.invalid/mapping/{label}",
        cloud_partition=catalog.partition.partition_code,
        authority_level="unknown",
        content_hash=digest,
        storage_path=path.name,
        captured_at=captured_at,
        is_current=True,
    )
    session.add(source)
    session.flush()
    snapshot = SnapshotRecord(
        source_document_id=source.id,
        source_id=f"synthetic_mapping_{label}",
        content_hash=digest,
        storage_path=path.name,
        manifest_path=f"{label}.json",
        content_type="text/html",
        content_length_bytes=len(raw),
        captured_at=captured_at,
        change_status="content_changed",
        is_current=True,
    )
    session.add(snapshot)
    session.flush()
    evidence = Evidence(
        source_document_id=source.id,
        snapshot_record_id=snapshot.id,
        content_hash=digest,
        locator="html:#synthetic",
        excerpt=excerpt,
        evidence_type="html_section",
        confidence=0.8,
        review_status="machine_extracted",
    )
    session.add(evidence)
    session.flush()
    for definition, value in zip(catalog.definitions, (cpu, memory), strict=True):
        session.add(
            ProductSpecification(
                product_id=catalog.product.id,
                sku_id=catalog.sku.id,
                definition_id=definition.id,
                numeric_value=Decimal(value),
                raw_value=str(value),
                raw_unit=definition.canonical_unit,
                canonical_value=str(value),
                canonical_unit=definition.canonical_unit,
                evidence_id=evidence.id,
            )
        )
    session.flush()
    normalize_specifications(
        session,
        provider_code="synthetic_mapping",
        product_code=catalog.product.code,
        run_key=f"synthetic_mapping_{label}",
    )
    rows = session.scalars(
        select(NormalizedSpecification).where(NormalizedSpecification.evidence_id == evidence.id)
    ).all()
    return Chain(source, snapshot, evidence, path, {row.canonical_field.code: row for row in rows})


@pytest.mark.parametrize("invalid", ["source", "snapshot", "raw_hash"])
def test_mapping_selects_newest_valid_cpu_and_memory_not_invalid_history(
    session: Session, catalog: Catalog, invalid: str
) -> None:
    old = _chain(session, catalog, "old", 2, 4)
    earlier_current = _chain(session, catalog, "earlier_current", 4, 8)
    newest_current = _chain(session, catalog, "newest_current", 8, 16)
    newer_invalid = _chain(session, catalog, "newer_invalid", 64, 128)
    for chain in (old, newer_invalid):
        if invalid == "source":
            chain.source.is_current = False
        elif invalid == "snapshot":
            chain.snapshot.is_current = False
            assert chain.source.is_current is True
        else:
            chain.raw_path.write_bytes(b"x" * chain.raw_path.stat().st_size)
    session.flush()

    assert set(newest_current.rows) == {CPU, MEMORY}
    for code in (CPU, MEMORY):
        assert (
            old.rows[code].id
            < earlier_current.rows[code].id
            < newest_current.rows[code].id
            < newer_invalid.rows[code].id
        )
    single = _sku_values(session, catalog.sku.id)
    bulk = _sku_values_for_skus(session, [catalog.sku.id])
    assert single == newest_current.rows
    assert bulk == {catalog.sku.id: newest_current.rows}
    assert _numeric_value(single, CPU) == Decimal(8)
    assert _numeric_value(single, MEMORY) == Decimal(16)
    assert session.scalar(select(func.count()).select_from(NormalizedSpecification)) == 8
    assert newest_current.source.authority_level == "unknown"
    assert newest_current.evidence.review_status == "machine_extracted"


def test_mapping_without_snapshot_returns_missing_cpu_and_memory(
    session: Session, catalog: Catalog
) -> None:
    chain = _chain(session, catalog, "snapshotless", 8, 16)
    chain.evidence.snapshot_record_id = None
    session.flush()

    assert set(chain.rows) == {CPU, MEMORY}
    assert chain.raw_path.is_file()
    single = _sku_values(session, catalog.sku.id)
    assert single == {}
    assert _sku_values_for_skus(session, [catalog.sku.id]) == {}
    assert _sku_values_for_skus(session, []) == {}
    assert _numeric_value(single, CPU) is None
    assert _numeric_value(single, MEMORY) is None
    assert session.scalar(select(func.count()).select_from(NormalizedSpecification)) == 2
