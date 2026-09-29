import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from cloud_expert.pricing.usage_type_capture import EXPECTED, SOURCE, validate_capture


def envelope() -> dict[str, Any]:
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "http_status_observed": 200,
        "source_id": SOURCE,
        "response_utf8_base64": base64.b64encode(
            json.dumps({"total_count": 100, "usage_types": [EXPECTED]}).encode()
        ).decode(),
    }


def test_synthetic_metadata_copy_preserves_bytes() -> None:
    item = envelope()
    raw, captured = validate_capture(item)
    assert base64.b64encode(raw).decode() == item["response_utf8_base64"]
    assert captured.tzinfo is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("http_status_observed", 403),
        ("source_id", "unapproved_source"),
        ("captured_at", "2020-01-01T00:00:00"),
        ("captured_at", (datetime.now(UTC) + timedelta(days=1)).isoformat()),
        ("response_utf8_base64", "not base64"),
    ],
)
def test_metadata_capture_rejects_unproven_scope(field: str, value: Any) -> None:
    item = envelope()
    item[field] = value
    with pytest.raises(ValueError):
        validate_capture(item)


@pytest.mark.parametrize(
    "data",
    [
        {"total_count": 100, "usage_types": [{**EXPECTED, "name": "different_scope"}]},
        {"total_count": 100, "usage_types": [EXPECTED], "account_id": "synthetic-private"},
        {"total_count": True, "usage_types": [EXPECTED]},
        {"total_count": 100, "usage_types": []},
    ],
)
def test_metadata_capture_rejects_changed_row_and_account_fields(data: dict[str, Any]) -> None:
    item = envelope()
    item["response_utf8_base64"] = base64.b64encode(json.dumps(data).encode()).decode()
    with pytest.raises(ValueError):
        validate_capture(item)
