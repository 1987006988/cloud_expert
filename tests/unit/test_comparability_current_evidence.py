"""Synthetic provenance chains only; SQLite is in-memory and raw files are temporary."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import file_digest, sha256
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.config.settings import get_settings
from cloud_expert.database.models.canonical import ComparabilityAssessment, NormalizedSpecification
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import SKU, Product, ProductCategory
from cloud_expert.database.models.product_extension import ServiceTier
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.normalization import evidence_validity
from cloud_expert.normalization.canonical_service import (
    FieldReadiness,
    _count_normalized,
    _normalized_readiness,
    _observed_qualifiers,
    assess_comparability,
    normalize_specifications,
)
from cloud_expert.normalization.evidence_validity import (
    HashCache,
    current_normalized_statement,
    normalized_evidence_valid,
)

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


@dataclass
class Chain:
    product: Product
    sku: SKU
    partition: CloudPartition
    source: SourceDocument
    snapshot: SnapshotRecord
    evidence: Evidence
    spec: ProductSpecification
    row: NormalizedSpecification
    path: Path


@pytest.fixture
def raw_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "synthetic_raw"
    root.mkdir()
    settings = replace(get_settings(), raw_data_dir=str(root))
    monkeypatch.setattr(evidence_validity, "get_settings", lambda: settings)
    return root


def _chain(
    session: Session,
    root: Path,
    *,
    provider_code: str = "aliyun",
    product_code: str = "ecs",
    qualifier: str = "baseline",
) -> Chain:
    token = uuid4().hex
    category = session.scalar(select(ProductCategory).where(ProductCategory.code == "compute"))
    if category is None:
        category = ProductCategory(code="compute", name="Synthetic compute")
        session.add(category)
        session.flush()
    provider = session.scalar(select(Provider).where(Provider.code == provider_code))
    if provider is None:
        provider = Provider(
            code=provider_code,
            name="Synthetic provider",
            display_name="Synthetic",
            provider_type="fixture",
        )
        session.add(provider)
        session.flush()
    partition = session.scalar(
        select(CloudPartition).where(CloudPartition.provider_id == provider.id)
    )
    if partition is None:
        partition = CloudPartition(
            provider_id=provider.id,
            partition_code=f"synthetic_{provider_code}",
            partition_name="Synthetic partition",
            market_mode="domestic",
            is_active=True,
        )
        session.add(partition)
    product = session.scalar(
        select(Product).where(Product.provider_id == provider.id, Product.code == product_code)
    )
    if product is None:
        product = Product(
            provider_id=provider.id,
            category_id=category.id,
            market_mode="domestic",
            code=product_code,
            official_name="Synthetic test product",
            display_name="Synthetic test product",
            product_status="unknown",
        )
        session.add(product)
        session.flush()
    sku = session.scalar(select(SKU).where(SKU.product_id == product.id))
    if sku is None:
        sku = SKU(
            product_id=product.id,
            provider_sku_code=f"{product_code}.synthetic.large",
            name="Synthetic SKU",
        )
        session.add(sku)
        session.flush()
    raw = f"Synthetic-only fixture {token}: baseline bandwidth 4 Gbps".encode()
    path = root / f"{token}.bin"
    path.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    source = SourceDocument(
        provider_id=provider.id,
        source_type="specification",
        title="Synthetic source, not official product evidence",
        url=f"https://example.invalid/synthetic/{token}",
        cloud_partition=partition.partition_code,
        authority_level="unknown",
        content_hash=digest,
        storage_path=path.name,
        is_current=True,
    )
    session.add(source)
    session.flush()
    snapshot = SnapshotRecord(
        source_document_id=source.id,
        source_id=f"synthetic_{token}",
        content_hash=digest,
        storage_path=path.name,
        manifest_path=f"{token}.json",
        content_type="text/plain",
        content_length_bytes=len(raw),
        captured_at=NOW,
        change_status="content_changed",
        is_current=True,
    )
    session.add(snapshot)
    session.flush()
    evidence = Evidence(
        source_document_id=source.id,
        snapshot_record_id=snapshot.id,
        content_hash=digest,
        locator="synthetic:bandwidth",
        excerpt=raw.decode(),
        evidence_type="html_section",
        confidence=0.8,
        review_status="machine_extracted",
    )
    session.add(evidence)
    session.flush()
    code = (
        "network.baseline_bandwidth_gbps"
        if qualifier == "baseline"
        else "network.max_bandwidth_gbps"
    )
    definition = session.scalar(
        select(SpecificationDefinition).where(SpecificationDefinition.code == code)
    )
    if definition is None:
        definition = SpecificationDefinition(
            code=code,
            name="Synthetic bandwidth",
            category_id=category.id,
            data_type="numeric",
            canonical_unit="Gbps",
        )
        session.add(definition)
        session.flush()
    spec = ProductSpecification(
        product_id=product.id,
        sku_id=sku.id,
        definition_id=definition.id,
        numeric_value=Decimal(4),
        raw_value="4",
        raw_unit="Gbps",
        canonical_value="4",
        canonical_unit="Gbps",
        evidence_id=evidence.id,
    )
    session.add(spec)
    session.flush()
    normalize_specifications(
        session,
        provider_code=provider_code,
        product_code=product_code,
        run_key=f"synthetic_{token}",
    )
    row = session.scalars(
        select(NormalizedSpecification).where(
            NormalizedSpecification.product_specification_id == spec.id
        )
    ).one()
    return Chain(product, sku, partition, source, snapshot, evidence, spec, row, path)


def _count(session: Session, chain: Chain, cache: HashCache | None = None) -> int:
    return _count_normalized(
        session,
        product_id=chain.product.id,
        canonical_field_id=chain.row.canonical_field_id,
        qualifier=chain.row.value_qualifier,
        hash_cache=cache,
        now=NOW,
    )


def _readiness(session: Session, chain: Chain, cache: HashCache | None = None) -> FieldReadiness:
    return _normalized_readiness(
        session,
        product_id=chain.product.id,
        canonical_field_id=chain.row.canonical_field_id,
        qualifier=chain.row.value_qualifier,
        hash_cache=cache,
        now=NOW,
    )


def test_complete_current_chain_is_counted_without_approving_synthetic_evidence(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    assert session.scalars(current_normalized_statement(now=NOW)).all() == [chain.row]
    assert normalized_evidence_valid(session, chain.row, now=NOW)
    assert _count(session, chain) == _readiness(session, chain).count == 1
    assert _readiness(session, chain).value_qualifiers == frozenset({"baseline"})
    assert chain.source.authority_level == "unknown"
    assert chain.evidence.review_status == chain.row.review_status == "machine_extracted"


@pytest.mark.parametrize(
    ("entity", "attribute", "value"),
    [
        ("source", "is_current", False),
        ("snapshot", "is_current", False),
        ("evidence", "review_status", "rejected"),
        ("row", "review_status", "rejected"),
        ("evidence", "snapshot_record_id", None),
        ("evidence", "content_hash", None),
        ("evidence", "content_hash", "b" * 64),
        ("source", "content_hash", "c" * 64),
        ("snapshot", "content_hash", "d" * 64),
        ("spec", "valid_to", NOW),
        ("spec", "valid_to", NOW - timedelta(seconds=1)),
        ("spec", "valid_from", NOW + timedelta(seconds=1)),
    ],
)
def test_database_prefilter_and_direct_check_reject_invalid_chain(
    session: Session,
    raw_root: Path,
    entity: str,
    attribute: str,
    value: object,
) -> None:
    chain = _chain(session, raw_root)
    setattr(getattr(chain, entity), attribute, value)
    session.flush()
    assert session.scalars(current_normalized_statement(now=NOW)).all() == []
    assert not normalized_evidence_valid(session, chain.row, now=NOW)
    assert _count(session, chain) == _readiness(session, chain).count == 0
    assert session.scalar(select(func.count()).select_from(NormalizedSpecification)) == 1


@pytest.mark.parametrize(
    ("entity", "attribute", "value"),
    [
        ("source", "storage_path", None),
        ("source", "storage_path", "missing.bin"),
        ("snapshot", "storage_path", "missing.bin"),
        ("snapshot", "content_length_bytes", 0),
        ("source", "cloud_partition", None),
        ("source", "cloud_partition", "unregistered"),
        ("partition", "is_active", False),
        ("partition", "market_mode", "international"),
        ("row", "scope_identity", "other.sku"),
        ("row", "scope_type", "unknown"),
    ],
)
def test_raw_and_scope_checks_fail_closed(
    session: Session, raw_root: Path, entity: str, attribute: str, value: object
) -> None:
    chain = _chain(session, raw_root)
    setattr(getattr(chain, entity), attribute, value)
    session.flush()
    assert not normalized_evidence_valid(session, chain.row, now=NOW)
    assert _count(session, chain) == _readiness(session, chain).count == 0


@pytest.mark.parametrize(
    "broken_link",
    [
        "normalized_evidence",
        "spec_evidence",
        "snapshot_source",
        "normalized_product",
        "normalized_sku",
        "spec_sku",
        "sku_product",
        "source_provider",
    ],
)
def test_cross_linked_real_structure_records_are_not_accepted(
    session: Session, raw_root: Path, broken_link: str
) -> None:
    chain = _chain(session, raw_root)
    other = _chain(session, raw_root, provider_code="aws", product_code="ec2")
    links = {
        "normalized_evidence": (chain.row, "evidence_id", other.evidence.id),
        "spec_evidence": (chain.spec, "evidence_id", other.evidence.id),
        "snapshot_source": (chain.snapshot, "source_document_id", other.source.id),
        "normalized_product": (chain.row, "product_id", other.product.id),
        "normalized_sku": (chain.row, "sku_id", other.sku.id),
        "spec_sku": (chain.spec, "sku_id", other.sku.id),
        "sku_product": (chain.sku, "product_id", other.product.id),
        "source_provider": (chain.source, "provider_id", other.source.provider_id),
    }
    obj, name, value = links[broken_link]
    setattr(obj, name, value)
    session.flush()
    assert not normalized_evidence_valid(session, chain.row, now=NOW)


def test_only_new_snapshot_values_and_qualifiers_are_observed(
    session: Session, raw_root: Path
) -> None:
    old = _chain(session, raw_root, qualifier="maximum")
    current = _chain(session, raw_root)
    old.snapshot.is_current = False
    session.flush()
    assert old.source.is_current is True  # The actual Source47/Snapshot47 failure shape.
    assert session.scalars(current_normalized_statement(now=NOW)).all() == [current.row]
    assert _count(session, old) == 0
    assert _count(session, current) == 1
    assert _observed_qualifiers(
        session, current.row.canonical_field_id, current.product.id, current.product.id, now=NOW
    ) == {"baseline"}
    assert session.scalar(select(func.count()).select_from(ProductSpecification)) == 2
    assert session.scalar(select(func.count()).select_from(NormalizedSpecification)) == 2


def test_snapshotless_synthetic_fixture_is_supported_as_invalid_not_business_valid(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    chain.evidence.snapshot_record_id = None
    chain.evidence.content_hash = None
    chain.source.storage_path = None
    chain.path.unlink()
    session.flush()
    assert not normalized_evidence_valid(session, chain.row, now=NOW)
    assert _readiness(session, chain).count == 0
    assert chain.source.url.startswith("https://example.invalid/")


def test_non_hex_equal_hashes_are_not_proof(session: Session, raw_root: Path) -> None:
    chain = _chain(session, raw_root)
    chain.evidence.content_hash = chain.source.content_hash = chain.snapshot.content_hash = "z" * 64
    session.flush()
    assert not normalized_evidence_valid(session, chain.row, now=NOW)


def test_equal_metadata_hashes_do_not_replace_raw_verification(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    chain.evidence.content_hash = chain.source.content_hash = chain.snapshot.content_hash = "a" * 64
    session.flush()
    assert session.scalars(current_normalized_statement(now=NOW)).all() == [chain.row]
    assert not normalized_evidence_valid(session, chain.row, now=NOW)
    assert _count(session, chain) == 0


@pytest.mark.parametrize("missing", ["product_specification_id", "evidence_id", "product_id"])
def test_direct_check_handles_missing_related_records_without_flushing(
    session: Session, raw_root: Path, missing: str
) -> None:
    chain = _chain(session, raw_root)
    setattr(chain.row, missing, 999999)
    assert not normalized_evidence_valid(session, chain.row, now=NOW)


def test_missing_snapshot_record_fails_closed_without_flushing(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    chain.evidence.snapshot_record_id = 999999
    assert not normalized_evidence_valid(session, chain.row, now=NOW)


def test_uppercase_hashes_and_absolute_paths_within_raw_root_are_valid(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    assert chain.evidence.content_hash is not None
    chain.evidence.content_hash = chain.evidence.content_hash.upper()
    chain.snapshot.storage_path = chain.source.storage_path = str(chain.path)
    session.flush()
    assert session.scalars(current_normalized_statement(now=NOW)).all() == [chain.row]
    assert normalized_evidence_valid(session, chain.row, now=NOW)


def test_raw_change_during_hashing_is_not_cached(
    session: Session, raw_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = _chain(session, raw_root)

    def change_after_digest(*args: object, **kwargs: object) -> object:
        digest = sha256(chain.path.read_bytes())
        chain.path.write_bytes(b"changed synthetic snapshot")
        return digest

    monkeypatch.setattr(evidence_validity, "file_digest", change_after_digest)
    cache: HashCache = {}
    assert not normalized_evidence_valid(session, chain.row, hash_cache=cache, now=NOW)
    assert cache == {}


def test_raw_hash_cache_is_reused_but_never_caches_validity(
    session: Session, raw_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = _chain(session, raw_root)
    tracked = Mock(wraps=file_digest)
    monkeypatch.setattr(evidence_validity, "file_digest", tracked)
    cache: HashCache = {}
    assert _count(session, chain, cache) == 1
    assert _readiness(session, chain, cache).count == 1
    assert tracked.call_count == len(cache) == 1
    chain.snapshot.is_current = False
    assert not normalized_evidence_valid(session, chain.row, hash_cache=cache, now=NOW)
    chain.snapshot.is_current = True
    chain.evidence.review_status = "rejected"
    assert not normalized_evidence_valid(session, chain.row, hash_cache=cache, now=NOW)
    chain.evidence.review_status = "machine_extracted"
    chain.spec.valid_to = NOW
    assert not normalized_evidence_valid(session, chain.row, hash_cache=cache, now=NOW)
    assert tracked.call_count == 1


def test_raw_mutation_and_removal_invalidate_cached_digest(
    session: Session, raw_root: Path
) -> None:
    import os

    chain = _chain(session, raw_root)
    cache: HashCache = {}
    assert normalized_evidence_valid(session, chain.row, hash_cache=cache, now=NOW)
    stat = chain.path.stat()
    chain.path.write_bytes(b"x" * stat.st_size)
    os.utime(chain.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert not normalized_evidence_valid(session, chain.row, hash_cache=cache, now=NOW)
    chain.path.unlink()
    assert not normalized_evidence_valid(session, chain.row, hash_cache=cache, now=NOW)


def test_raw_paths_cannot_escape_configured_root(session: Session, raw_root: Path) -> None:
    chain = _chain(session, raw_root)
    outside = raw_root.parent / "outside.bin"
    outside.write_bytes(chain.path.read_bytes())
    for path in ("../outside.bin", str(outside)):
        chain.snapshot.storage_path = chain.source.storage_path = path
        assert not normalized_evidence_valid(session, chain.row, now=NOW)


def test_raw_read_error_fails_closed(
    session: Session, raw_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = _chain(session, raw_root)

    denied = Mock(side_effect=PermissionError("synthetic unreadable snapshot"))
    monkeypatch.setattr(evidence_validity, "file_digest", denied)
    assert not normalized_evidence_valid(session, chain.row, now=NOW)


def test_pending_evidence_is_not_erased_by_machine_normalized_status(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    chain.evidence.review_status = "pending_review"
    session.flush()
    ready = _readiness(session, chain)
    assert ready.count == ready.pending_review_count == 1
    assert chain.row.review_status == "machine_extracted"


def test_validity_checks_do_not_flush_or_modify_review_history(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    chain.evidence.review_status = chain.row.review_status = "human_reviewed"
    chain.evidence.reviewed_by = "synthetic_historical_reviewer"
    chain.evidence.reviewed_at = NOW
    session.flush()
    chain.source.title = "unflushed synthetic change"
    assert normalized_evidence_valid(session, chain.row, now=NOW)
    assert _count(session, chain) == 1
    stored = (
        session.connection()
        .execute(select(SourceDocument.title).where(SourceDocument.id == chain.source.id))
        .scalar_one()
    )
    assert stored != chain.source.title
    assert chain.evidence.review_status == chain.row.review_status == "human_reviewed"
    assert chain.evidence.reviewed_by == "synthetic_historical_reviewer"
    assert chain.evidence.reviewed_at == NOW


def test_spec_validity_is_half_open_and_handles_naive_sqlite_datetimes(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    chain.spec.valid_from = NOW.replace(tzinfo=None)
    chain.spec.valid_to = (NOW + timedelta(seconds=1)).replace(tzinfo=None)
    session.flush()
    assert normalized_evidence_valid(session, chain.row, now=NOW)
    assert _count(session, chain) == 1
    assert not normalized_evidence_valid(session, chain.row, now=NOW + timedelta(seconds=1))


def test_product_and_service_tier_scopes_require_product_ownership(
    session: Session, raw_root: Path
) -> None:
    chain = _chain(session, raw_root)
    chain.spec.sku_id = chain.row.sku_id = None
    chain.row.scope_type = "product"
    chain.row.scope_identity = f"product:{chain.product.id}"
    session.flush()
    assert normalized_evidence_valid(session, chain.row, now=NOW)
    chain.row.scope_type = "service_tier"
    chain.row.scope_identity = "synthetic-tier"
    assert not normalized_evidence_valid(session, chain.row, now=NOW)
    tier = ServiceTier(
        product_id=chain.product.id,
        tier_code="synthetic-tier",
        official_name="Synthetic tier",
        review_status="machine_extracted",
    )
    session.add(tier)
    session.flush()
    assert normalized_evidence_valid(session, chain.row, now=NOW)
    tier.review_status = "rejected"
    session.flush()
    assert not normalized_evidence_valid(session, chain.row, now=NOW)


def test_reassessment_retires_old_machine_qualifier_without_deleting_history(
    session: Session, raw_root: Path
) -> None:
    a = _chain(session, raw_root)
    b = _chain(session, raw_root, provider_code="aws", product_code="ec2")
    assess_comparability(session)
    assessment = session.scalars(
        select(ComparabilityAssessment).where(
            ComparabilityAssessment.canonical_field_id == a.row.canonical_field_id,
            ComparabilityAssessment.value_qualifier == "baseline",
        )
    ).one()
    assert assessment.status == "comparable"
    identity = assessment.id
    a.snapshot.is_current = b.snapshot.is_current = False
    session.flush()
    assess_comparability(session)
    assert assessment.id == identity
    assert assessment.status == "not_comparable"
    assert assessment.reason_code == "missing_both_sides"
    assert session.scalar(select(func.count()).select_from(NormalizedSpecification)) == 2


def test_human_and_rejected_assessments_and_normalized_labels_are_preserved(
    session: Session, raw_root: Path
) -> None:
    a = _chain(session, raw_root)
    b = _chain(session, raw_root, provider_code="aws", product_code="ec2")
    assess_comparability(session)
    assessment = session.scalars(
        select(ComparabilityAssessment).where(
            ComparabilityAssessment.canonical_field_id == a.row.canonical_field_id
        )
    ).one()
    for status in ("human_reviewed", "rejected"):
        assessment.review_status = a.row.review_status = status
        session.flush()
        previous = (
            assessment.status,
            assessment.reason_code,
            assessment.updated_at,
            a.row.numeric_value,
            a.row.updated_at,
        )
        a.snapshot.is_current = b.snapshot.is_current = False
        session.flush()
        summary = assess_comparability(session)
        assert summary.status_counts.get("comparable", 0) == 0
        normalize_specifications(
            session,
            provider_code="aliyun",
            product_code="ecs",
            run_key="synthetic_preserve_history",
        )
        assert (
            assessment.status,
            assessment.reason_code,
            assessment.updated_at,
            a.row.numeric_value,
            a.row.updated_at,
        ) == previous
        assert assessment.review_status == a.row.review_status == status
