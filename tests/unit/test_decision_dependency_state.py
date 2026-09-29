from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloud_expert.decision import dependency_state
from cloud_expert.decision.dependency_state import implementation_state, raw_digest


def test_digest_changes_when_raw_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "raw.bin"
    path.write_bytes(b"synthetic original")
    original = raw_digest("raw.bin", raw_root=tmp_path)
    assert original == sha256(b"synthetic original").hexdigest()
    path.write_bytes(b"synthetic tamper")
    assert raw_digest("raw.bin", raw_root=tmp_path) != original


def test_missing_or_outside_file_has_no_digest(tmp_path: Path) -> None:
    assert raw_digest(None, raw_root=tmp_path) is None
    assert raw_digest("missing.bin", raw_root=tmp_path) is None
    assert raw_digest("../outside.bin", raw_root=tmp_path) is None


def test_implementation_state_tracks_code_changes_only(tmp_path: Path) -> None:
    source = tmp_path / "engine.py"
    source.write_text("value = 1\n", encoding="utf-8")
    first = implementation_state(package_root=tmp_path)
    (tmp_path / "private.env").write_text("excluded", encoding="utf-8")
    assert implementation_state(package_root=tmp_path) == first
    source.write_text("value = 2\n", encoding="utf-8")
    assert implementation_state(package_root=tmp_path) != first
    assert first[0]["path"] == "engine.py"


def test_implementation_state_requires_source_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unavailable"):
        implementation_state(package_root=tmp_path)


def _registration(status: str = "approved") -> SimpleNamespace:
    return SimpleNamespace(
        source_id="synthetic_source",
        enabled=True,
        terms_review_status=status,
        automated_fetch_allowed=status == "approved",
        manual_only=False,
        model_dump=lambda **kwargs: {"source_id": "synthetic_source", "terms": status},
    )


def test_registry_permission_change_invalidates_fingerprint(monkeypatch) -> None:
    monkeypatch.setattr(dependency_state, "load_registry_entries", lambda: [_registration()])
    original = dependency_state.registry_state()
    monkeypatch.setattr(
        dependency_state, "load_registry_entries", lambda: [_registration("disallowed")]
    )
    revoked = dependency_state.registry_state()
    assert original["synthetic_source"]["sha256"] != revoked["synthetic_source"]["sha256"]
    assert not revoked["synthetic_source"]["automated_fetch_allowed"]


def test_duplicate_registration_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        dependency_state, "load_registry_entries", lambda: [_registration(), _registration()]
    )
    with pytest.raises(ValueError, match="duplicate"):
        dependency_state.registry_state()


def test_invalid_registry_is_not_an_empty_valid_state(monkeypatch) -> None:
    def invalid():
        raise ValueError("synthetic schema violation")

    monkeypatch.setattr(dependency_state, "load_registry_entries", invalid)
    with pytest.raises(ValueError, match="schema violation"):
        dependency_state.registry_state()
