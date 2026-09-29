"""Synthetic offline EC2 selection; never fetch or approve real prices."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from test_official_catalog import NOW, SKU, TERM, fixture, inputs

from cloud_expert.pricing import large_catalog as large


def run(
    tmp_path: Path,
    *,
    payload: dict[str, Any] | None = None,
    raw: bytes | None = None,
    manifest_update: dict[str, Any] | None = None,
    entry_update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry, base, selection = fixture("AmazonEC2")
    if entry_update:
        entry = entry.model_copy(update=entry_update)
    encoded, manifest = inputs(payload if payload is not None else base, entry)
    if raw is not None:
        encoded = raw
        manifest.update(
            content_length_bytes=len(raw), content_sha256=hashlib.sha256(raw).hexdigest()
        )
    manifest.update(manifest_update or {})
    path = tmp_path / "synthetic_catalog.json"
    path.write_bytes(encoded)
    before_manifest = copy.deepcopy(manifest)
    result = large.inspect_large_ec2_catalog(
        path, entry=entry, manifest=manifest, selections=[selection], as_of=NOW, max_age_days=7
    )
    assert manifest == before_manifest
    assert path.read_bytes() == encoded
    return result


def test_selects_all_tiers_preserves_original_identity(tmp_path: Path) -> None:
    _, payload, _ = fixture("AmazonEC2")
    payload["products"]["UNSELECTED"] = {"note": "no scope approval"}
    payload["terms"]["OnDemand"]["UNSELECTED"] = {"incomplete": True}
    payload["terms"]["Reserved"] = {SKU: {"not": "OnDemand"}}
    result = run(tmp_path, payload=payload)
    assert result["original_snapshot_integrity_verified"] is True
    assert result["full_catalog_semantically_validated"] is False
    assert result["selected_envelope_is_official_snapshot"] is False
    assert result["selected_envelope_sha256"] != result["raw_sha256"]
    assert result["selected_envelope_content_length_bytes"] < result["raw_content_length_bytes"]
    assert set(result["selected_envelope"]["products"]) == {SKU}
    assert set(result["selected_envelope"]["terms"]) == {"OnDemand"}
    assert (
        result["selected_envelope"]["terms"]["OnDemand"][SKU] == payload["terms"]["OnDemand"][SKU]
    )
    assert [r["unit_price"] for r in result["records"]] == ["0.1234567890", "0.10"]
    assert [r["end_range"] for r in result["records"]] == ["100", "Inf"]
    assert result["records"][0]["product_locator"] == f"/products/{SKU}"
    assert result["customer_eligible"] is False
    assert result["tax_status"] == "unverified"
    assert result["database_write_performed"] is False
    assert result["fetching_performed"] is False


@pytest.mark.parametrize(
    "update",
    [
        {"content_sha256": "0" * 64},
        {"content_sha256": "not-a-hash"},
        {"content_length_bytes": 1},
        {"content_length_bytes": 0},
        {"content_length_bytes": True},
        {"content_length_bytes": large.MAX_RAW_BYTES + 1},
        {"requested_url": "https://example.com"},
        {"final_url": "https://example.com"},
        {"source_id": "different"},
        {"content_type": "text/html"},
        {"schema_version": "2"},
        {"http_status": 206},
        {"captured_at": "2020-01-01T00:00:00Z"},
        {"captured_at": "2027-01-01T00:00:00Z"},
    ],
)
def test_rejects_raw_integrity_and_provenance(tmp_path: Path, update: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        run(tmp_path, manifest_update=update)


@pytest.mark.parametrize(
    "update",
    [
        {"product_code": "s3"},
        {"provider_code": "aliyun"},
        {"market_mode": "domestic"},
        {"cloud_partition": "aws_cn"},
        {"terms_review_status": "pending"},
        {"robots_allowed": False},
        {"allow_automated_fetch": False},
        {"automated_fetch_allowed": False},
        {"enabled": False},
        {"manual_only": True},
        {"requires_authentication": True},
        {"requires_browser": True},
        {
            "url": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/eu-west-1/index.json"
        },
        {
            "url": "https://pricing.us-east-1.amazonaws.com.evil.invalid/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json"
        },
    ],
)
def test_rejects_unauthorized_sources(tmp_path: Path, update: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        run(tmp_path, entry_update=update)


@pytest.mark.parametrize("suffix", [b"garbage", b"{}", b",", b"\xff"])
def test_reads_and_validates_tail_after_selected_skus(tmp_path: Path, suffix: bytes) -> None:
    entry, payload, _ = fixture("AmazonEC2")
    raw, _ = inputs(payload, entry)
    with pytest.raises(ValueError):
        run(tmp_path, raw=raw + suffix)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"{}", b'{"products":[]}', b'{"a":'])
def test_invalid_structure_and_truncation(tmp_path: Path, raw: bytes) -> None:
    with pytest.raises(ValueError):
        run(tmp_path, raw=raw)


@pytest.mark.parametrize("field", ["metadata", "selected", "skipped", "sku", "terms"])
def test_rejects_duplicate_keys_everywhere(tmp_path: Path, field: str) -> None:
    entry, payload, _ = fixture("AmazonEC2")
    raw, _ = inputs(payload, entry)
    if field == "metadata":
        raw = raw.replace(b'"formatVersion":', b'"formatVersion":"v1.0","formatVersion":')
    elif field == "selected":
        raw = raw.replace(b'"sku":', b'"sku":"duplicate","sku":', 1)
    elif field == "sku":
        raw = raw.replace(b'"products": {', b'"products": {"' + SKU.encode() + b'":{},')
    elif field == "terms":
        raw = raw.replace(b'"OnDemand":', b'"OnDemand":{},"OnDemand":')
    else:
        raw = raw[:-1] + b',"skipped":{"x":1,"x":2}}'
    with pytest.raises(ValueError, match="duplicate"):
        run(tmp_path, raw=raw)


@pytest.mark.parametrize(
    "case",
    [
        "missing_product",
        "missing_terms",
        "wrong_region",
        "tier_gap",
        "multi_offer",
        "numeric_price",
    ],
)
def test_reuses_price_scope_and_completeness_guards(tmp_path: Path, case: str) -> None:
    _, payload, _ = fixture("AmazonEC2")
    terms = payload["terms"]["OnDemand"][SKU]
    if case == "missing_product":
        payload["products"].clear()
    elif case == "missing_terms":
        payload["terms"]["OnDemand"].clear()
    elif case == "wrong_region":
        payload["products"][SKU]["attributes"]["regionCode"] = "cn-north-1"
    elif case == "tier_gap":
        terms[TERM]["priceDimensions"][f"{TERM}.TEST1"]["beginRange"] = "101"
    elif case == "multi_offer":
        terms["SECOND"] = copy.deepcopy(terms[TERM])
    else:
        terms[TERM]["priceDimensions"][f"{TERM}.TEST0"]["pricePerUnit"]["USD"] = 0.1
    with pytest.raises(ValueError):
        run(tmp_path, payload=payload)


def test_literal_dotted_key_cannot_impersonate_path(tmp_path: Path) -> None:
    _, payload, _ = fixture("AmazonEC2")
    payload[f"products.{SKU}"] = payload["products"].pop(SKU)
    with pytest.raises(ValueError):
        run(tmp_path, payload=payload)


def test_metadata_after_terms_and_reversed_order(tmp_path: Path) -> None:
    _, payload, _ = fixture("AmazonEC2")
    result = run(tmp_path, payload=dict(reversed(list(payload.items()))))
    assert len(result["records"]) == 2


def test_escaped_strings_across_tiny_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(large, "READ_CHUNK_BYTES", 3)
    _, payload, _ = fixture("AmazonEC2")
    payload["disclaimer"] = 'SYNTHETIC: \\path, "quoted", unicode \u4e2d\u6587'
    result = run(tmp_path, payload=payload)
    assert result["disclaimer"] == payload["disclaimer"]
    assert json.dumps(result["selected_envelope"])


def test_bounded_reads_and_skipped_objects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = large._VerifiedReader.read
    sizes = []

    def guarded_read(self: large._VerifiedReader, size: int = -1) -> bytes:
        assert 0 <= size <= large.READ_CHUNK_BYTES
        sizes.append(size)
        return original(self, size)

    monkeypatch.setattr(large._VerifiedReader, "read", guarded_read)
    _, payload, _ = fixture("AmazonEC2")
    payload["skipped"] = [{"description": "synthetic " * 1000} for _ in range(250)]
    result = run(tmp_path, payload=payload)
    assert result["raw_content_length_bytes"] > 2_000_000
    assert result["selected_envelope_content_length_bytes"] < 4000
    assert len(sizes) > 30


@pytest.mark.parametrize(
    "name,value",
    [
        ("MAX_SELECTED_BYTES", 80),
        ("MAX_DEPTH", 3),
        ("MAX_ACTIVE_KEYS", 4),
        ("MAX_ACTIVE_KEY_BYTES", 20),
    ],
)
def test_resource_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: int
) -> None:
    monkeypatch.setattr(large, name, value)
    with pytest.raises(ValueError, match="limit|bounded"):
        run(tmp_path)


def test_hard_limit_enforced_during_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(large, "MAX_RAW_BYTES", 8)
    reader = large._VerifiedReader(io.BytesIO(b" " * 9), 9)
    with pytest.raises(ValueError, match="hard limit"):
        reader.read(9)


def test_unbounded_reads_forbidden() -> None:
    reader = large._VerifiedReader(io.BytesIO(b"{}"), 2)
    with pytest.raises(ValueError, match="unbounded"):
        reader.read()


@pytest.mark.parametrize("quoted", [True, False])
def test_token_limit_across_read_boundaries(quoted: bool) -> None:
    raw = (b'"' if quoted else b"") + b"1" * (large.MAX_TOKEN_BYTES + 1)
    reader = large._VerifiedReader(io.BytesIO(raw), len(raw))
    reader.read(large.READ_CHUNK_BYTES)
    with pytest.raises(ValueError, match="token limit"):
        reader.read(large.READ_CHUNK_BYTES)


def test_missing_dependency_has_no_whole_file_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(large.importlib, "import_module", missing)
    with pytest.raises(ValueError, match="ijson"):
        run(tmp_path)


def test_empty_and_duplicate_selections_fail_before_open(tmp_path: Path) -> None:
    entry, payload, selection = fixture("AmazonEC2")
    _, manifest = inputs(payload, entry)
    for selections in ([], [selection, selection]):
        with pytest.raises(ValueError, match="unique"):
            large.inspect_large_ec2_catalog(
                tmp_path / "does_not_exist",
                entry=entry,
                manifest=manifest,
                selections=selections,
                as_of=NOW,
                max_age_days=7,
            )


def test_over_50_mib_original_with_small_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, payload, selection = fixture("AmazonEC2")
    original_policy = entry.fetch_policy.model_dump()
    raw, manifest = inputs(payload, entry)
    path = tmp_path / "synthetic_large_catalog.json"
    digest = hashlib.sha256()
    block = b" " * large.READ_CHUNK_BYTES
    with path.open("wb") as stream:
        for _ in range(832):  # 52 MiB of legal JSON whitespace, not real vendor data.
            stream.write(block)
            digest.update(block)
        stream.write(raw)
        digest.update(raw)
    manifest.update(content_sha256=digest.hexdigest(), content_length_bytes=path.stat().st_size)
    assert manifest["content_length_bytes"] > entry.fetch_policy.max_content_length_bytes

    def forbid_read_bytes(self: Path) -> bytes:
        raise AssertionError("whole-file reads are forbidden")

    monkeypatch.setattr(Path, "read_bytes", forbid_read_bytes)
    result = large.inspect_large_ec2_catalog(
        path, entry=entry, manifest=manifest, selections=[selection], as_of=NOW, max_age_days=7
    )
    assert result["raw_sha256"] == digest.hexdigest()
    assert result["raw_content_length_bytes"] == 832 * len(block) + len(raw)
    assert result["selected_envelope_content_length_bytes"] < 4000
    assert entry.fetch_policy.model_dump() == original_policy


def test_snapshot_mutation_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = large.os.fstat
    calls = 0

    def changed(fd: int) -> Any:
        nonlocal calls
        calls += 1
        value = original(fd)
        if calls == 1:
            return value
        from types import SimpleNamespace

        return SimpleNamespace(st_size=value.st_size, st_mtime_ns=value.st_mtime_ns + 1)

    monkeypatch.setattr(large.os, "fstat", changed)
    with pytest.raises(ValueError, match="changed during"):
        run(tmp_path)


def test_partial_tier_is_not_promoted(tmp_path: Path) -> None:
    _, payload, _ = fixture("AmazonEC2")
    dimensions = payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"]
    del dimensions[f"{TERM}.TEST1"]
    with pytest.raises(ValueError, match="terminal tier"):
        run(tmp_path, payload=payload)


def test_large_catalog_uses_same_documented_route_authorization(tmp_path: Path) -> None:
    result = run(tmp_path, entry_update={"robots_allowed": None, "robots_checked_at": None})
    assert result["source_authorization"]["robots_policy"] == "not_applicable_api_route"
    assert result["source_authorization"]["recorded_robots_allowed"] is None
    assert result["full_catalog_semantically_validated"] is False


@pytest.mark.parametrize(
    "update",
    [
        {"robots_allowed": False},
        {"reviewed_at": None},
        {"automated_fetch_allowed": False},
        {"terms_review_status": "pending"},
        {"url": "https://aws.amazon.com/ec2/pricing/on-demand/"},
    ],
)
def test_large_api_route_keeps_source_guards(tmp_path: Path, update: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        run(tmp_path, entry_update={"robots_allowed": None, "robots_checked_at": None, **update})
