"""Local auth provenance is not permission to transmit account metadata."""

import json

import pytest

from cloud_expert.model_review.decision_panel import _runtime_sensitivity


def _raw(payload, kind="session_meta"):
    return json.dumps({"type": kind, "payload": payload}).encode()


@pytest.mark.parametrize("key", ["creator_user_id", "creator_account_id"])
def test_only_verified_native_auth_provenance_has_local_exception(key):
    raw = _raw({key: "synthetic-local-auth-identifier"})
    assert _runtime_sensitivity(raw) == ["sensitive_metadata_key"]
    assert _runtime_sensitivity(raw, verified_isolated_native=True) == []


@pytest.mark.parametrize("key", ["creator_user_id", "creator_account_id"])
@pytest.mark.parametrize("kind", ["response_item", "world_state", "turn_context", "item.completed"])
def test_same_keys_elsewhere_are_not_exempt(key, kind):
    assert _runtime_sensitivity(
        _raw({key: "synthetic-local-auth-identifier"}, kind), verified_isolated_native=True
    ) == ["sensitive_metadata_key"]


@pytest.mark.parametrize(
    "payload",
    [
        {"nested": {"creator_user_id": "synthetic-private"}},
        {"creator_user_id": {"value": "synthetic-private"}},
        {"creator_user_id": ["synthetic-private"]},
        {"creator_account_id": "not an opaque identifier"},
        {"creator_user_id": "x" * 129},
        {"chatgpt_account_id": "synthetic-private"},
        {"customer_id": "synthetic-private"},
        {"embedded": json.dumps({"creator_user_id": "synthetic-private"})},
        {"creator_user_id": "synthetic-local", "api_key": "synthetic-secret-value"},
        {"creator_user_id": "synthetic-local", "note": "Bearer synthetic-secret-value"},
        {"creator_user_id": "example@example.invalid"},
    ],
)
def test_local_metadata_exception_cannot_hide_other_private_content(payload):
    assert _runtime_sensitivity(_raw(payload), verified_isolated_native=True)


def test_local_scan_never_changes_original_bytes():
    original = _raw({"creator_user_id": "synthetic-local-auth-identifier"})
    copied = bytes(original)
    _runtime_sensitivity(original, verified_isolated_native=True)
    assert original == copied


def test_same_named_nested_path_cannot_impersonate_root_session_metadata():
    raw = json.dumps(
        {
            "type": "response_item",
            "session_meta": {"payload": {"creator_user_id": "synthetic-private"}},
        }
    ).encode()
    assert _runtime_sensitivity(raw, verified_isolated_native=True) == ["sensitive_metadata_key"]


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("kind", ["session_meta", "response_item"])
def test_escaped_secret_values_are_scanned_after_json_decoding(verified, kind):
    raw = _raw({"creator_user_id": "sk-" + "syntheticsecretvalue"}, kind).replace(
        b"sk-", b"sk\\u002d"
    )
    assert "sensitive_value_pattern" in _runtime_sensitivity(raw, verified_isolated_native=verified)


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_escaped_json_keys_are_scanned_after_decoding(verified, nested):
    payload = {"sk-" + "syntheticsecretvalue": "not-a-secret-value"}
    raw = _raw(payload) if nested else json.dumps(payload).encode()
    raw = raw.replace(b"sk-", b"sk\\u002d")
    assert "sensitive_value_pattern" in _runtime_sensitivity(raw, verified_isolated_native=verified)
