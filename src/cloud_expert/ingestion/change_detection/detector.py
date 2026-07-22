from typing import Any

from cloud_expert.database.enums import ChangeStatus
from cloud_expert.ingestion.change_detection.models import ChangeReport, FieldChange
from cloud_expert.ingestion.storage.manifest import SnapshotManifest

COMPARE_FIELDS = (
    "http_status",
    "final_url",
    "content_type",
    "content_length_bytes",
    "content_sha256",
)
METADATA_FIELDS = (
    "title",
    "json_top_level_type",
    "pdf_page_count",
    "is_pdf_encrypted",
)


def _field_value(manifest: SnapshotManifest, field: str) -> Any:
    if hasattr(manifest, field):
        return getattr(manifest, field)
    return manifest.content_metadata.get(field)


def detect_change(
    source_id: str,
    current: SnapshotManifest,
    previous: SnapshotManifest | None,
) -> ChangeReport:
    if previous is None:
        return ChangeReport(
            source_id=source_id,
            previous_snapshot_id=None,
            current_snapshot_id=current.snapshot_id,
            change_status=ChangeStatus.FIRST_SEEN.value,
            changes=[],
        )

    changes: list[FieldChange] = []
    for field in (*COMPARE_FIELDS, *METADATA_FIELDS):
        old_value = _field_value(previous, field)
        new_value = _field_value(current, field)
        if old_value != new_value:
            changes.append(FieldChange(field=field, old_value=old_value, new_value=new_value))

    if not changes:
        status = ChangeStatus.UNCHANGED.value
    elif any(change.field == "content_sha256" for change in changes):
        status = ChangeStatus.CONTENT_CHANGED.value
    elif any(change.field == "final_url" for change in changes):
        status = ChangeStatus.REDIRECT_CHANGED.value
    elif any(change.field == "content_type" for change in changes):
        status = ChangeStatus.CONTENT_TYPE_CHANGED.value
    else:
        status = ChangeStatus.METADATA_CHANGED.value

    return ChangeReport(
        source_id=source_id,
        previous_snapshot_id=previous.snapshot_id,
        current_snapshot_id=current.snapshot_id,
        change_status=status,
        changes=changes,
    )
