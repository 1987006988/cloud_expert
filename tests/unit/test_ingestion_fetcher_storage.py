import json
import uuid
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from cloud_expert.database.models.ingestion import IngestionRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore


def _raw_dir(name: str) -> Path:
    path = Path("test_outputs") / f"{name}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _entry(source_id: str):
    entry = get_entry_by_source_id(source_id, Path("data/source_registry"))
    assert entry is not None
    return entry


def test_first_and_duplicate_html_fetch_create_one_snapshot(session: Session) -> None:
    entry = _entry("synthetic_html_fixture")
    fetcher = SourceFetcher(snapshot_store=SnapshotStore(_raw_dir("html_duplicate")))

    first = fetcher.fetch(entry, session=session)
    second = fetcher.fetch(entry, session=session)

    assert first.status == "succeeded"
    assert first.change_status == "first_seen"
    assert second.status == "unchanged"
    assert second.change_status == "unchanged"
    assert session.query(IngestionRun).count() == 2
    assert session.query(SnapshotRecord).count() == 1


def test_html_content_change_creates_new_snapshot(session: Session) -> None:
    entry = _entry("synthetic_html_fixture")
    raw_dir = _raw_dir("html_changed")
    fetcher = SourceFetcher(snapshot_store=SnapshotStore(raw_dir))

    first = fetcher.fetch(entry, session=session)
    changed_file = raw_dir / "changed.html"
    changed_file.write_text(
        "<html><head><title>Synthetic HTML Fixture Changed</title></head><body>changed</body></html>",
        encoding="utf-8",
    )
    changed_entry = entry.model_copy(update={"fixture_response_path": str(changed_file.resolve())})
    second = fetcher.fetch(changed_entry, session=session, force=True)

    assert first.snapshot_id != second.snapshot_id
    assert second.status == "succeeded"
    assert second.change_status == "content_changed"
    assert session.query(SnapshotRecord).count() == 2
    latest = json.loads(
        (fetcher.snapshot_store.latest_pointer_path(entry)).read_text(encoding="utf-8")
    )
    assert latest["snapshot_id"] == second.snapshot_id


def test_json_and_pdf_fetch(session: Session) -> None:
    raw_dir = _raw_dir("json_pdf")
    fetcher = SourceFetcher(snapshot_store=SnapshotStore(raw_dir))

    json_outcome = fetcher.fetch(_entry("synthetic_json_fixture"), session=session)
    pdf_outcome = fetcher.fetch(_entry("synthetic_pdf_fixture"), session=session)

    assert json_outcome.status == "succeeded"
    assert pdf_outcome.status == "succeeded"
    assert session.query(SnapshotRecord).count() == 2


def test_domain_violation_is_blocked_before_content_file(session: Session) -> None:
    entry = _entry("synthetic_html_fixture")
    blocked_entry = entry.model_copy(update={"url": "http://127.0.0.1/private"})
    raw_dir = _raw_dir("blocked_domain")
    outcome = SourceFetcher(snapshot_store=SnapshotStore(raw_dir)).fetch(
        blocked_entry, session=session
    )

    assert outcome.status == "blocked"
    assert outcome.error_code == "domain_not_allowed"
    assert not list(raw_dir.rglob("raw.bin"))
    assert session.query(IngestionRun).count() == 1


def test_file_too_large_fails_without_snapshot(session: Session) -> None:
    entry = _entry("synthetic_html_fixture")
    small_policy = entry.fetch_policy.model_copy(update={"max_content_length_bytes": 8})
    tiny_entry = entry.model_copy(update={"fetch_policy": small_policy})
    raw_dir = _raw_dir("too_large")
    outcome = SourceFetcher(snapshot_store=SnapshotStore(raw_dir)).fetch(
        tiny_entry, session=session
    )

    assert outcome.status == "failed"
    assert outcome.error_code == "file_too_large"
    assert not list(raw_dir.rglob("manifest.json"))


def test_redirect_to_private_ip_is_blocked(session: Session) -> None:
    entry = _entry("synthetic_html_fixture")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "http://127.0.0.1/private"}, request=request
        )

    outcome = SourceFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        snapshot_store=SnapshotStore(_raw_dir("redirect_blocked")),
    ).fetch(entry, session=session)

    assert outcome.status == "blocked"
    assert outcome.error_code == "redirect_violation"


def test_retry_count_is_bounded() -> None:
    entry = _entry("synthetic_html_fixture")
    policy = entry.fetch_policy.model_copy(update={"max_retries": 2, "retry_backoff_seconds": 0})
    retry_entry = entry.model_copy(update={"fetch_policy": policy})
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, request=request)

    outcome = SourceFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        snapshot_store=SnapshotStore(_raw_dir("retry")),
    ).fetch(retry_entry)

    assert outcome.status == "failed"
    assert outcome.error_code == "http_error"
    assert calls["count"] == 3
