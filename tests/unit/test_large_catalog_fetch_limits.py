from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore


def _ec2_entry() -> SourceRegistryEntry:
    entry = get_entry_by_source_id("aws_ec2_pricing_bulk_us_east_1", Path("data/source_registry"))
    assert entry is not None
    return entry


def test_reviewed_ec2_catalog_accepts_bounded_large_capture() -> None:
    assert _ec2_entry().fetch_policy.max_content_length_bytes == 536_870_912


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", "aws_ec2_other"),
        ("product_code", "s3"),
        ("cloud_partition", "aws_cn"),
        ("market_mode", "domestic"),
        ("terms_review_status", "unknown"),
        ("url", "https://pricing.us-east-1.amazonaws.com/another.json"),
    ],
)
def test_large_capture_exception_is_exactly_scoped(field: str, value: str) -> None:
    data = _ec2_entry().model_dump()
    data[field] = value
    with pytest.raises(ValidationError, match="large catalog limit is restricted"):
        SourceRegistryEntry.model_validate(data)


def test_large_capture_has_absolute_ceiling() -> None:
    data = _ec2_entry().model_dump()
    data["fetch_policy"]["max_content_length_bytes"] = 536_870_913
    with pytest.raises(ValidationError):
        SourceRegistryEntry.model_validate(data)


def test_oversized_header_is_rejected_before_reading_body(tmp_path: Path) -> None:
    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("oversized body must not be downloaded")
            yield b""  # pragma: no cover

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "536870913", "Content-Type": "application/json"},
            stream=UnreadableStream(),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        outcome = SourceFetcher(client=client, snapshot_store=SnapshotStore(tmp_path)).fetch(
            _ec2_entry()
        )
    assert outcome.error_code == "file_too_large"
    assert not list(tmp_path.rglob("manifest.json"))


def test_incorrect_small_header_cannot_bypass_actual_byte_limit(tmp_path: Path) -> None:
    entry = _ec2_entry()
    entry = entry.model_copy(
        update={
            "fetch_policy": entry.fetch_policy.model_copy(update={"max_content_length_bytes": 3})
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "1", "Content-Type": "application/json"},
            content=b'{"x": 1}',
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        outcome = SourceFetcher(client=client, snapshot_store=SnapshotStore(tmp_path)).fetch(entry)
    assert outcome.error_code == "file_too_large"
    assert not list(tmp_path.rglob("manifest.json"))
