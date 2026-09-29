"""Controlled public metadata copy import; never imports API request headers."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.result import HttpFetchResult
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing.huawei_promotion import _get_or_create_evidence

SOURCE = "huawei_cloud_obs_standard_single_az_usage_type_api"
URL = (
    "https://bss.myhuaweicloud.com/v2/products/usage-types"
    "?resource_type_code=hws.resource.type.obs&offset=93&limit=1"
)
RULE = "huawei_obs_size_usage_type_copy_v1"
EXPECTED = {
    "code": "size",
    "name": "标准存储单AZ容量",
    "resource_type_code": "hws.resource.type.obs",
    "service_type_code": "hws.service.type.obs",
    "resource_type_name": "云存储",
    "service_type_name": "对象存储服务",
}


def validate_capture(envelope: dict[str, Any]) -> tuple[bytes, datetime]:
    if (
        set(envelope)
        != {"captured_at", "http_status_observed", "source_id", "response_utf8_base64"}
        or envelope["source_id"] != SOURCE
        or envelope["http_status_observed"] != 200
    ):
        raise ValueError("Metadata capture scope or successful status is missing")
    captured = datetime.fromisoformat(envelope["captured_at"])
    if captured.tzinfo is None or captured > datetime.now(UTC):
        raise ValueError("Invalid metadata capture timestamp")
    raw = base64.b64decode(envelope["response_utf8_base64"], validate=True)
    if not raw or len(raw) > 4096:
        raise ValueError("Metadata response size is invalid")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or set(data) != {"total_count", "usage_types"}
        or not isinstance(data["total_count"], int)
        or isinstance(data["total_count"], bool)
        or data["total_count"] <= 93
        or data["usage_types"] != [EXPECTED]
    ):
        raise ValueError("Official size factor row differs or contains unexpected data")
    return raw, captured


def import_usage_capture(
    session: Session, envelope: dict[str, Any], *, store: SnapshotStore | None = None
) -> dict[str, Any]:
    raw, captured = validate_capture(envelope)
    entry = get_entry_by_source_id(SOURCE)
    if (
        entry is None
        or entry.url != URL
        or entry.provider_code != "huawei_cloud"
        or entry.product_code != "obs"
        or entry.cloud_partition != "huawei_cn"
        or entry.terms_review_status != "approved"
        or not entry.manual_only
        or not entry.requires_authentication
        or entry.allow_automated_fetch
    ):
        raise ValueError("Metadata source is not approved for this controlled import")
    store = store or SnapshotStore()
    stored = store.store(
        entry=entry,
        requested_url=URL,
        final_url=URL,
        http_status=200,
        content_type="application/json",
        content=raw,
        response_headers={},
        content_metadata={
            "capture_method": "official_api_explorer_response_clipboard_copy",
            "wire_response_bytes_available": False,
            "http_status_observed": 200,
            "request_headers_stored": False,
            "classification": "official_public_billing_metadata",
            "api_size_quote_time_basis_proven": False,
        },
        fetch_duration_ms=0,
        captured_at=captured,
    )
    fetched = HttpFetchResult(
        URL, URL, 200, {}, raw, "application/json", "utf-8", captured, captured, 0, 0
    )
    snapshot_id = SourceFetcher(snapshot_store=store)._record_success(
        session, entry, fetched, stored
    )
    from cloud_expert.database.models.snapshot import SnapshotRecord

    snapshot = session.get(SnapshotRecord, snapshot_id)
    assert snapshot is not None
    evidence = _get_or_create_evidence(
        session,
        snapshot,
        "json:$.usage_types[0]",
        json.dumps(EXPECTED, ensure_ascii=False, sort_keys=True),
        RULE,
    )
    session.commit()
    return {
        "source_document_id": snapshot.source_document_id,
        "snapshot_record_id": snapshot.id,
        "evidence_id": evidence.id,
        "snapshot_created": stored.created,
        "raw_sha256": snapshot.content_hash,
        "api_size_quote_time_basis_proven": False,
        "price_snapshots_created": 0,
    }
