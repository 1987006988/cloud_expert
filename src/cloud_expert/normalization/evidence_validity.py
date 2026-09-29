"""Read-only current provenance checks, not evidence approval or customer eligibility."""

from collections.abc import MutableMapping
from datetime import UTC, datetime
from hashlib import file_digest
from pathlib import Path
from stat import S_ISREG

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, contains_eager

from cloud_expert.config.settings import get_settings
from cloud_expert.database.enums import ReviewStatus
from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ServiceTier
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification

type HashCache = MutableMapping[tuple[str, int, int, int, int, int], str]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def current_normalized_statement(
    *,
    now: datetime | None = None,
) -> Select[tuple[NormalizedSpecification]]:
    """Database prefilter; callers MUST also call normalized_evidence_valid for raw SHA/scope.

    Missing links, including snapshot-less synthetic fixtures, are excluded.
    The query never flushes, writes, approves, or deletes anything. ProductSpecification
    has no review_status column; rejection lives on its Evidence and normalized row.
    """
    at = _utc(now or datetime.now(UTC))
    return (
        select(NormalizedSpecification)
        .join(
            ProductSpecification,
            NormalizedSpecification.product_specification_id == ProductSpecification.id,
        )
        .join(Evidence, NormalizedSpecification.evidence_id == Evidence.id)
        .join(SourceDocument, Evidence.source_document_id == SourceDocument.id)
        .join(SnapshotRecord, Evidence.snapshot_record_id == SnapshotRecord.id)
        .join(Product, NormalizedSpecification.product_id == Product.id)
        .where(
            NormalizedSpecification.review_status != ReviewStatus.REJECTED.value,
            Evidence.review_status != ReviewStatus.REJECTED.value,
            ProductSpecification.evidence_id == Evidence.id,
            ProductSpecification.product_id == Product.id,
            ProductSpecification.sku_id.is_not_distinct_from(NormalizedSpecification.sku_id),
            SourceDocument.provider_id == Product.provider_id,
            SourceDocument.is_current.is_(True),
            SnapshotRecord.is_current.is_(True),
            SnapshotRecord.source_document_id == SourceDocument.id,
            func.length(Evidence.content_hash) == 64,
            func.lower(Evidence.content_hash) == func.lower(SourceDocument.content_hash),
            func.lower(Evidence.content_hash) == func.lower(SnapshotRecord.content_hash),
            or_(ProductSpecification.valid_from.is_(None), ProductSpecification.valid_from <= at),
            or_(ProductSpecification.valid_to.is_(None), ProductSpecification.valid_to > at),
        )
        .options(
            contains_eager(NormalizedSpecification.product_specification),
            contains_eager(NormalizedSpecification.product),
            contains_eager(NormalizedSpecification.evidence).contains_eager(
                Evidence.source_document
            ),
        )
        .execution_options(autoflush=False)
    )


def normalized_evidence_valid(
    session: Session,
    row: NormalizedSpecification,
    *,
    hash_cache: HashCache | None = None,
    now: datetime | None = None,
) -> bool:
    """Check current provenance, links, provider/market/entity scope and raw SHA-256.

    Safe for direct callers as well as rows returned by current_normalized_statement.
    Missing files/links/hashes fail closed, including synthetic fixtures without raw
    snapshots. Tests can use isolated, real-structure snapshots under their configured
    raw root. True proves provenance integrity only, never official authority, review
    approval, factual correctness, or customer eligibility.

    Pass a fresh {} for hash_cache per operation. Only actual file digests are cached,
    keyed by resolved path and stat identity; current/rejection/expiry is checked each
    call. No global cache, autoflush, persistence, or audit-label changes are performed.
    """
    at = _utc(now or datetime.now(UTC))
    with session.no_autoflush:
        spec = session.get(ProductSpecification, row.product_specification_id)
        evidence = session.get(Evidence, row.evidence_id)
        product = session.get(Product, row.product_id)
        if (
            spec is None
            or evidence is None
            or product is None
            or row.review_status == ReviewStatus.REJECTED.value
            or evidence.review_status == ReviewStatus.REJECTED.value
            or spec.evidence_id != evidence.id
            or spec.product_id != product.id
            or spec.sku_id != row.sku_id
            or (spec.valid_from is not None and _utc(spec.valid_from) > at)
            or (spec.valid_to is not None and _utc(spec.valid_to) <= at)
            or evidence.snapshot_record_id is None
        ):
            return False
        source = session.get(SourceDocument, evidence.source_document_id)
        snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
        if (
            source is None
            or snapshot is None
            or not source.is_current
            or not snapshot.is_current
            or snapshot.source_document_id != source.id
            or source.provider_id != product.provider_id
            or not _hashes_match(evidence.content_hash, source.content_hash, snapshot.content_hash)
            or not _scope_valid(session, row, product, source)
        ):
            return False
        try:
            root = Path(get_settings().raw_data_dir).resolve(strict=True)
            raw_path = _raw_path(root, snapshot.storage_path)
            if raw_path is None or _raw_path(root, source.storage_path) != raw_path:
                return False
            return _raw_hash_matches(raw_path, snapshot, hash_cache)
        except (OSError, ValueError, RuntimeError):
            return False


def _hashes_match(*values: str | None) -> bool:
    return (
        all(
            value is not None
            and len(value) == 64
            and all(c in "0123456789abcdefABCDEF" for c in value)
            for value in values
        )
        and len({value.lower() for value in values if value is not None}) == 1
    )


def _scope_valid(
    session: Session, row: NormalizedSpecification, product: Product, source: SourceDocument
) -> bool:
    partition = session.scalar(
        select(CloudPartition).where(
            CloudPartition.provider_id == product.provider_id,
            CloudPartition.partition_code == source.cloud_partition,
            CloudPartition.market_mode == product.market_mode,
            CloudPartition.is_active.is_(True),
        )
    )
    if partition is None or not row.scope_identity:
        return False
    if row.sku_id is not None:
        sku = session.get(SKU, row.sku_id)
        return (
            row.scope_type == "sku"
            and sku is not None
            and sku.product_id == product.id
            and row.scope_identity == sku.provider_sku_code
        )
    if row.scope_type == "product":
        return row.scope_identity == f"product:{product.id}"
    if row.scope_type == "service_tier":
        return (
            session.scalar(
                select(ServiceTier.id).where(
                    ServiceTier.product_id == product.id,
                    ServiceTier.tier_code == row.scope_identity,
                    ServiceTier.review_status != ReviewStatus.REJECTED.value,
                )
            )
            is not None
        )
    if row.scope_type == "product_family":
        return (
            session.scalar(
                select(ProductFamily.id).where(
                    ProductFamily.product_id == product.id,
                    ProductFamily.family_code == row.scope_identity,
                    ProductFamily.review_status != ReviewStatus.REJECTED.value,
                )
            )
            is not None
        )
    # Other scopes need an explicit ownership proof, not just a nonempty identity.
    return False


def _raw_path(root: Path, stored: str | None) -> Path | None:
    if not stored:
        return None
    path = (root / stored.replace("\\", "/")).resolve(strict=True)
    return path if path.is_relative_to(root) else None


def _raw_hash_matches(path: Path, snapshot: SnapshotRecord, cache: HashCache | None) -> bool:
    before = path.stat()
    if not S_ISREG(before.st_mode) or before.st_size != snapshot.content_length_bytes:
        return False
    key = (
        str(path),
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    digest = cache.get(key) if cache is not None else None
    if digest is None:
        with path.open("rb") as handle:
            digest = file_digest(handle, "sha256").hexdigest()
        after = path.stat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != key[
            1:
        ]:
            return False
        if cache is not None:
            cache[key] = digest
    return digest == snapshot.content_hash.lower()
