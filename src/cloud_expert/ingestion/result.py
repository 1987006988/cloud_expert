from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class HttpFetchResult:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    content_type: str
    encoding: str | None
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    retry_count: int

    @property
    def content_length_bytes(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class IngestionOutcome:
    source_id: str
    status: str
    requested_url: str
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    bytes_downloaded: int | None = None
    retry_count: int = 0
    duration_ms: int | None = None
    snapshot_id: str | None = None
    snapshot_record_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    change_status: str | None = None
    manifest_path: str | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
