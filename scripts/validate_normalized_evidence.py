import json
from hashlib import sha256
from pathlib import Path
from typing import cast

import _bootstrap  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.database.session import SessionLocal

RAW_ROOT = Path("data/raw")
_HASH_CACHE: dict[Path, str] = {}


def main() -> int:
    with SessionLocal() as session:
        total = int(session.scalar(select(func.count()).select_from(NormalizedSpecification)) or 0)
        issues = _validate_rows(session)
    result: dict[str, object] = {
        "normalized_specifications": total,
        "missing_product_specification": issues["missing_product_specification"],
        "missing_evidence_links": issues["missing_evidence_links"],
        "evidence_mismatch": issues["evidence_mismatch"],
        "missing_source_document": issues["missing_source_document"],
        "missing_snapshot_record": issues["missing_snapshot_record"],
        "missing_manifest": issues["missing_manifest"],
        "missing_raw_file": issues["missing_raw_file"],
        "hash_mismatch": issues["hash_mismatch"],
        "checked_raw_files": len(_HASH_CACHE),
        "samples": issues["samples"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failure_count = sum(
        _issue_count(result, key) for key in result if key.startswith(("missing_", "hash_"))
    )
    failure_count += _issue_count(result, "evidence_mismatch")
    return 1 if failure_count else 0


def _validate_rows(session: Session) -> dict[str, object]:
    issues: dict[str, object] = {
        "missing_product_specification": 0,
        "missing_evidence_links": 0,
        "evidence_mismatch": 0,
        "missing_source_document": 0,
        "missing_snapshot_record": 0,
        "missing_manifest": 0,
        "missing_raw_file": 0,
        "hash_mismatch": 0,
        "samples": [],
    }
    samples = cast("list[dict[str, object]]", issues["samples"])
    rows = session.scalars(select(NormalizedSpecification).order_by(NormalizedSpecification.id))
    for normalized in rows:
        spec = session.get(ProductSpecification, normalized.product_specification_id)
        if spec is None:
            _record(issues, samples, normalized.id, "missing_product_specification")
            continue
        evidence = session.get(Evidence, normalized.evidence_id)
        if evidence is None:
            _record(issues, samples, normalized.id, "missing_evidence_links")
            continue
        if spec.evidence_id != normalized.evidence_id:
            _record(issues, samples, normalized.id, "evidence_mismatch")
        source_document = session.get(SourceDocument, evidence.source_document_id)
        if source_document is None:
            _record(issues, samples, normalized.id, "missing_source_document")
            continue
        if evidence.snapshot_record_id is None:
            _record(issues, samples, normalized.id, "missing_snapshot_record")
            continue
        snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
        if snapshot is None:
            _record(issues, samples, normalized.id, "missing_snapshot_record")
            continue
        _validate_snapshot_files(issues, samples, normalized.id, snapshot)
    return issues


def _validate_snapshot_files(
    issues: dict[str, object],
    samples: list[dict[str, object]],
    normalized_id: int,
    snapshot: SnapshotRecord,
) -> None:
    manifest_path = _raw_path(snapshot.manifest_path)
    raw_path = _raw_path(snapshot.storage_path)
    if not manifest_path.exists():
        _record(issues, samples, normalized_id, "missing_manifest")
        return
    if not raw_path.exists():
        _record(issues, samples, normalized_id, "missing_raw_file")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_hash = _file_hash(raw_path)
    if raw_hash != snapshot.content_hash or raw_hash != manifest.get("content_sha256"):
        _record(issues, samples, normalized_id, "hash_mismatch")


def _record(
    issues: dict[str, object],
    samples: list[dict[str, object]],
    normalized_id: int,
    reason: str,
) -> None:
    issues[reason] = _issue_count(issues, reason) + 1
    if len(samples) < 20:
        samples.append({"normalized_specification_id": normalized_id, "reason": reason})


def _issue_count(values: dict[str, object], key: str) -> int:
    value = values[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} is not an integer counter")
    return value


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
