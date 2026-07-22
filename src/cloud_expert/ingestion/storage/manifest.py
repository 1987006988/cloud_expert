from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    snapshot_id: str
    source_id: str
    provider_code: str
    market_mode: str
    product_code: str | None
    source_type: str
    requested_url: str
    final_url: str
    captured_at: datetime
    http_status: int
    content_type: str
    content_length_bytes: int = Field(ge=0)
    content_sha256: str
    normalized_sha256: str | None = None
    normalization_version: str | None = None
    storage_path: str
    response_headers_path: str
    metadata_path: str
    change_report_path: str | None = None
    is_duplicate_content: bool = False
    previous_snapshot_id: str | None = None
    change_status: str
    fetch_duration_ms: int = Field(ge=0)
    collector_version: str = "0.1.0"
    content_metadata: dict[str, Any] = Field(default_factory=dict)
