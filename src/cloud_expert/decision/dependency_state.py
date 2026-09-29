"""Current source state for invalidating decisions after evidence changes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.evidence_packages.references import freshness_for
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.model_review.pilot import RAW_ROOT


def implementation_state(*, package_root: Path | None = None) -> list[dict[str, str]]:
    """Bind cached decisions to the local implementations that produced them."""
    root = package_root or Path(__file__).resolve().parents[1]
    paths = sorted(root.rglob("*.py"))
    if not paths:
        raise ValueError("Decision implementation files are unavailable")
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ]


def raw_digest(storage_path: str | None, *, raw_root: Path = RAW_ROOT) -> str | None:
    if not storage_path:
        return None
    root = raw_root.resolve()
    path = (root / storage_path).resolve()
    if not path.is_relative_to(root):
        return None
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None


def current_source_state(session: Session, now: datetime) -> list[dict[str, Any]]:
    registry = registry_state()
    snapshots: dict[int, list[dict[str, Any]]] = {}
    for row in session.scalars(select(SnapshotRecord).order_by(SnapshotRecord.id)):
        snapshots.setdefault(row.source_document_id, []).append(
            {
                "id": row.id,
                "source_id": row.source_id,
                "content_hash": row.content_hash,
                "storage_path": row.storage_path,
                "is_current": row.is_current,
                "registry": registry.get(row.source_id, {"status": "missing"}),
            }
        )
    digests: dict[str | None, str | None] = {}
    rows = []
    for source in session.scalars(select(SourceDocument).order_by(SourceDocument.id)):
        if source.storage_path not in digests:
            digests[source.storage_path] = raw_digest(source.storage_path)
        rows.append(
            {
                "id": source.id,
                "provider_id": source.provider_id,
                "cloud_partition": source.cloud_partition,
                "url": source.url,
                "authority_level": source.authority_level,
                "content_hash": source.content_hash,
                "raw_content_hash": digests[source.storage_path],
                "is_current": source.is_current,
                "freshness": freshness_for(source, now),
                "captured_at": source.captured_at,
                "snapshots": snapshots.get(source.id, []),
            }
        )
    return rows


def registry_state() -> dict[str, dict[str, Any]]:
    """Permission-only changes must invalidate Decision inputs and cached reviews."""
    result: dict[str, dict[str, Any]] = {}
    for entry in load_registry_entries():
        if entry.source_id in result:
            raise ValueError("ambiguous duplicate source registration")
        payload = entry.model_dump(mode="json", exclude={"registry_file"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        result[entry.source_id] = {
            "status": "registered",
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "enabled": entry.enabled,
            "terms_review_status": str(entry.terms_review_status),
            "automated_fetch_allowed": entry.automated_fetch_allowed,
            "manual_only": entry.manual_only,
        }
    return result
