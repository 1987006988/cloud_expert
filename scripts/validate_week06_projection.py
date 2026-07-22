import json
from hashlib import sha256
from pathlib import Path

import _bootstrap  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.ingestion import IngestionRun
from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.models.product import SKU, Product
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
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.database.session import SessionLocal

RAW_ROOT = Path("data/raw")

ENTITY_MODELS = {
    "provider": Provider,
    "product": Product,
    "product_family": ProductFamily,
    "sku": SKU,
    "service_tier": ServiceTier,
    "region": Region,
    "availability_zone": AvailabilityZone,
    "availability": Availability,
    "zone_availability": ZoneAvailability,
    "product_sla": ProductSLA,
    "source_document": SourceDocument,
    "snapshot_record": SnapshotRecord,
    "evidence": Evidence,
    "product_specification": ProductSpecification,
    "parsed_field_candidate": ParsedFieldCandidate,
    "parsing_run": ParsingRun,
    "ingestion_run": IngestionRun,
    "cloud_partition": CloudPartition,
    "review_item": ReviewItem,
    "normalized_specification": NormalizedSpecification,
}

REQUIRED_NONZERO = {
    "product_family",
    "sku",
    "service_tier",
    "region",
    "availability",
    "product_sla",
    "source_document",
    "snapshot_record",
    "evidence",
    "product_specification",
    "parsed_field_candidate",
    "parsing_run",
    "ingestion_run",
    "review_item",
    "normalized_specification",
}

SAMPLE_PLAN = {
    ("huawei_cloud", "ecs"): 10,
    ("aws", "ec2"): 10,
    ("aliyun", "ecs"): 10,
    ("huawei_cloud", "obs"): 5,
    ("aws", "s3"): 5,
    ("aliyun", "oss"): 5,
}

_HASH_CACHE: dict[Path, str] = {}


def main() -> int:
    with SessionLocal() as session:
        result = validate_projection(session)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


def validate_projection(session: Session) -> dict[str, object]:
    counts = _entity_counts(session)
    structural_errors = _structural_errors(session, counts)
    chain_errors = _chain_errors(session)
    samples = _sample_products(session)
    chain_failure_count = sum(chain_errors.values())
    sample_failures = 0
    for sample in samples.values():
        failed = sample["failed"]
        if isinstance(failed, int):
            sample_failures += failed
    result: dict[str, object] = {
        "counts": counts,
        "structural_errors": structural_errors,
        "chain_errors": chain_errors,
        "sample_results": samples,
    }
    result["valid"] = not structural_errors and chain_failure_count == 0 and sample_failures == 0
    return result


def _entity_counts(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, model in ENTITY_MODELS.items():
        if model is None:
            continue
        counts[name] = int(session.scalar(select(func.count()).select_from(model)) or 0)
    return counts


def _structural_errors(session: Session, counts: dict[str, int]) -> list[str]:
    errors = [
        f"{name}: count is zero" for name in sorted(REQUIRED_NONZERO) if counts.get(name, 0) == 0
    ]
    orphan_normalized = int(
        session.scalar(
            select(func.count())
            .select_from(NormalizedSpecification)
            .outerjoin(
                ProductSpecification,
                NormalizedSpecification.product_specification_id == ProductSpecification.id,
            )
            .where(ProductSpecification.id.is_(None))
        )
        or 0
    )
    if orphan_normalized:
        errors.append(f"normalized_specification: {orphan_normalized} orphan rows")
    return errors


def _chain_errors(session: Session) -> dict[str, int]:
    errors = {
        "missing_product_specification": 0,
        "missing_evidence": 0,
        "missing_source_document": 0,
        "missing_snapshot_record": 0,
        "missing_manifest": 0,
        "missing_raw_file": 0,
        "hash_mismatch": 0,
    }
    rows = session.scalars(select(NormalizedSpecification.id).order_by(NormalizedSpecification.id))
    for normalized_id in rows:
        reason = _validate_chain(session, int(normalized_id))
        if reason:
            errors[reason] += 1
    return errors


def _sample_products(session: Session) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for (provider_code, product_code), expected in SAMPLE_PLAN.items():
        product = _get_product(session, provider_code, product_code)
        label = f"{provider_code}/{product_code}"
        if product is None:
            results[label] = {
                "expected": expected,
                "sampled": 0,
                "passed": 0,
                "failed": expected,
                "failure_reasons": {"missing_product": expected},
            }
            continue
        ids = list(
            session.scalars(
                select(NormalizedSpecification.id)
                .where(NormalizedSpecification.product_id == product.id)
                .order_by(NormalizedSpecification.id)
                .limit(expected)
            )
        )
        failures: dict[str, int] = {}
        for normalized_id in ids:
            reason = _validate_chain(session, int(normalized_id))
            if reason:
                failures[reason] = failures.get(reason, 0) + 1
        if len(ids) < expected:
            failures["insufficient_sample"] = expected - len(ids)
        failed = sum(failures.values())
        results[label] = {
            "expected": expected,
            "sampled": len(ids),
            "passed": len(ids) - sum(v for k, v in failures.items() if k != "insufficient_sample"),
            "failed": failed,
            "failure_reasons": failures,
        }
    return results


def _get_product(session: Session, provider_code: str, product_code: str) -> Product | None:
    return session.scalar(
        select(Product)
        .join(Product.provider)
        .where(Product.code == product_code, Product.provider.has(code=provider_code))
    )


def _validate_chain(session: Session, normalized_id: int) -> str | None:
    normalized = session.get(NormalizedSpecification, normalized_id)
    if normalized is None:
        return "missing_product_specification"
    spec = session.get(ProductSpecification, normalized.product_specification_id)
    if spec is None:
        return "missing_product_specification"
    evidence = session.get(Evidence, normalized.evidence_id)
    if evidence is None:
        return "missing_evidence"
    source_document = session.get(SourceDocument, evidence.source_document_id)
    if source_document is None:
        return "missing_source_document"
    if evidence.snapshot_record_id is None:
        return "missing_snapshot_record"
    snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
    if snapshot is None:
        return "missing_snapshot_record"
    return _validate_snapshot(snapshot)


def _validate_snapshot(snapshot: SnapshotRecord) -> str | None:
    manifest_path = _raw_path(snapshot.manifest_path)
    raw_path = _raw_path(snapshot.storage_path)
    if not manifest_path.exists():
        return "missing_manifest"
    if not raw_path.exists():
        return "missing_raw_file"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_hash = _file_hash(raw_path)
    if raw_hash != snapshot.content_hash or raw_hash != manifest.get("content_sha256"):
        return "hash_mismatch"
    return None


def _raw_path(value: str) -> Path:
    normalized = str(value).replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute():
        return path
    if normalized == str(RAW_ROOT).replace("\\", "/") or normalized.startswith("data/raw/"):
        return path
    return RAW_ROOT / path


def _file_hash(path: Path) -> str:
    if path not in _HASH_CACHE:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        _HASH_CACHE[path] = digest.hexdigest()
    return _HASH_CACHE[path]


if __name__ == "__main__":
    raise SystemExit(main())
