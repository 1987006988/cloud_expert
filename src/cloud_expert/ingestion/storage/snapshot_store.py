import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cloud_expert.config.settings import get_settings
from cloud_expert.database.enums import ChangeStatus
from cloud_expert.ingestion.change_detection.detector import detect_change
from cloud_expert.ingestion.change_detection.models import ChangeReport
from cloud_expert.ingestion.change_detection.reporter import write_change_report
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.security.headers import sanitize_response_headers
from cloud_expert.ingestion.security.path_safety import ensure_within_directory, safe_path_segment
from cloud_expert.ingestion.storage.atomic_write import atomic_write_bytes, atomic_write_text
from cloud_expert.ingestion.storage.hashing import sha256_hex
from cloud_expert.ingestion.storage.manifest import SnapshotManifest


@dataclass(frozen=True)
class StoredSnapshot:
    manifest: SnapshotManifest
    manifest_path: Path
    created: bool
    change_report: ChangeReport


def _content_filename(content_type: str) -> str:
    media_type = content_type.split(";", 1)[0].lower()
    if media_type == "text/html":
        return "content.html"
    if media_type == "application/json":
        return "content.json"
    if media_type == "application/pdf":
        return "content.pdf"
    return "content.bin"


class SnapshotStore:
    def __init__(self, raw_data_dir: Path | None = None) -> None:
        self.raw_data_dir = (raw_data_dir or Path(get_settings().raw_data_dir)).resolve()

    def source_root(self, entry: SourceRegistryEntry) -> Path:
        product_code = entry.product_code or "unknown_product"
        path = self.raw_data_dir.joinpath(
            safe_path_segment(str(entry.market_mode)),
            safe_path_segment(entry.provider_code),
            safe_path_segment(product_code),
            safe_path_segment(entry.source_id),
        )
        return ensure_within_directory(self.raw_data_dir, path)

    def latest_pointer_path(self, entry: SourceRegistryEntry) -> Path:
        return self.source_root(entry) / "latest.json"

    def load_manifest(self, manifest_path: Path) -> SnapshotManifest:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return SnapshotManifest.model_validate(data)

    def latest_manifest(self, entry: SourceRegistryEntry) -> tuple[SnapshotManifest, Path] | None:
        latest_path = self.latest_pointer_path(entry)
        if not latest_path.exists():
            return None
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        manifest_path = self.raw_data_dir / data["manifest_path"]
        return self.load_manifest(manifest_path), manifest_path

    def find_manifest_by_hash(
        self,
        entry: SourceRegistryEntry,
        content_hash: str,
    ) -> tuple[SnapshotManifest, Path] | None:
        root = self.source_root(entry)
        if not root.exists():
            return None
        for manifest_path in sorted(root.rglob("manifest.json")):
            manifest = self.load_manifest(manifest_path)
            if manifest.content_sha256 == content_hash:
                return manifest, manifest_path
        return None

    def store(
        self,
        *,
        entry: SourceRegistryEntry,
        requested_url: str,
        final_url: str,
        http_status: int,
        content_type: str,
        content: bytes,
        response_headers: dict[str, str],
        content_metadata: dict[str, object],
        fetch_duration_ms: int,
        captured_at: datetime | None = None,
    ) -> StoredSnapshot:
        captured = captured_at or datetime.now(UTC)
        content_hash = sha256_hex(content)
        previous = self.latest_manifest(entry)
        duplicate = self.find_manifest_by_hash(entry, content_hash)
        if duplicate is not None:
            previous_manifest = previous[0] if previous else None
            report = detect_change(entry.source_id, duplicate[0], previous_manifest)
            unchanged_report = report.model_copy(
                update={"change_status": ChangeStatus.UNCHANGED.value}
            )
            return StoredSnapshot(
                manifest=duplicate[0].model_copy(update={"is_duplicate_content": True}),
                manifest_path=duplicate[1],
                created=False,
                change_report=unchanged_report,
            )

        snapshot_id = uuid.uuid4().hex
        timestamp = captured.strftime("%Y%m%dT%H%M%SZ")
        hash_short = content_hash[:8]
        snapshot_dir = (
            self.source_root(entry)
            / captured.strftime("%Y")
            / captured.strftime("%m")
            / f"{timestamp}_{hash_short}"
        )
        snapshot_dir = ensure_within_directory(self.raw_data_dir, snapshot_dir)
        if snapshot_dir.exists():
            msg = f"snapshot directory already exists: {snapshot_dir}"
            raise FileExistsError(msg)

        raw_path = snapshot_dir / "raw.bin"
        content_path = snapshot_dir / _content_filename(content_type)
        metadata_path = snapshot_dir / "metadata.json"
        headers_path = snapshot_dir / "response_headers.json"
        manifest_path = snapshot_dir / "manifest.json"
        change_report_path = snapshot_dir / "change_report.json"

        previous_manifest = previous[0] if previous else None
        draft_manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            source_id=entry.source_id,
            provider_code=entry.provider_code,
            market_mode=str(entry.market_mode),
            product_code=entry.product_code,
            source_type=str(entry.source_type),
            requested_url=requested_url,
            final_url=final_url,
            captured_at=captured,
            http_status=http_status,
            content_type=content_type,
            content_length_bytes=len(content),
            content_sha256=content_hash,
            storage_path=str(raw_path.relative_to(self.raw_data_dir)),
            response_headers_path=str(headers_path.relative_to(self.raw_data_dir)),
            metadata_path=str(metadata_path.relative_to(self.raw_data_dir)),
            change_report_path=str(change_report_path.relative_to(self.raw_data_dir)),
            previous_snapshot_id=previous_manifest.snapshot_id if previous_manifest else None,
            change_status=ChangeStatus.UNKNOWN.value,
            fetch_duration_ms=fetch_duration_ms,
            content_metadata=content_metadata,
        )
        report = detect_change(entry.source_id, draft_manifest, previous_manifest)
        manifest = draft_manifest.model_copy(update={"change_status": report.change_status})

        atomic_write_bytes(raw_path, content)
        if content_path.name != "raw.bin":
            atomic_write_bytes(content_path, content)
        atomic_write_text(
            metadata_path, json.dumps(content_metadata, ensure_ascii=False, indent=2, default=str)
        )
        atomic_write_text(
            headers_path,
            json.dumps(sanitize_response_headers(response_headers), ensure_ascii=False, indent=2),
        )
        write_change_report(change_report_path, report)
        atomic_write_text(manifest_path, manifest.model_dump_json(indent=2))
        atomic_write_text(
            self.latest_pointer_path(entry),
            json.dumps(
                {
                    "snapshot_id": manifest.snapshot_id,
                    "manifest_path": str(manifest_path.relative_to(self.raw_data_dir)),
                    "content_sha256": manifest.content_sha256,
                    "captured_at": manifest.captured_at.isoformat(),
                },
                indent=2,
            ),
        )
        return StoredSnapshot(
            manifest=manifest,
            manifest_path=manifest_path,
            created=True,
            change_report=report,
        )
