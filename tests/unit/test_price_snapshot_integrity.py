from hashlib import sha256
from types import SimpleNamespace

import pytest

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.pricing import extraction


def test_price_payload_hash_and_path_are_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(extraction, "_raw_data_dir", lambda: tmp_path)
    data = b'{"synthetic_price": "1.25"}'
    (tmp_path / "raw.bin").write_bytes(data)
    snapshot = SnapshotRecord(storage_path="raw.bin", content_hash=sha256(data).hexdigest())
    assert extraction._decode_payload(snapshot) == data.decode()
    (tmp_path / "raw.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        extraction._decode_payload(snapshot)
    snapshot.storage_path = "../outside.bin"
    with pytest.raises(ValueError, match="escapes"):
        extraction._decode_payload(snapshot)


def test_revoked_source_never_reaches_price_parser(session, monkeypatch):
    snapshot = SnapshotRecord(source_id=extraction.AWS_S3_STANDARD_SOURCE_ID)
    monkeypatch.setattr(extraction, "current_pricing_snapshots", lambda _: [(snapshot, None)])
    monkeypatch.setattr(
        extraction,
        "load_registry_entries",
        lambda: [SimpleNamespace(source_id=snapshot.source_id, terms_review_status="disallowed")],
    )

    def unexpected(*args):
        pytest.fail("Revoked collection permission reached evidence or price generation")

    monkeypatch.setattr(extraction, "ensure_snapshot_evidence", unexpected)
    monkeypatch.setattr(extraction, "_extract_aws_s3_standard_storage", unexpected)
    assert extraction.extract_price_records(session) == []
