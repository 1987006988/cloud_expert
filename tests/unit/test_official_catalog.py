"""Synthetic catalog fixtures only; no business database or real-price approval."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.pricing.official_catalog import (
    CatalogSelection,
    decode_catalog_json,
    inspect_official_catalog,
)

NOW = datetime(2026, 9, 30, tzinfo=UTC)
SKU = "SYNTHETICSKU00001"
TERM = f"{SKU}.JRTCKXETXF"


def fixture(
    service: str = "AmazonS3",
) -> tuple[SourceRegistryEntry, dict[str, Any], CatalogSelection]:
    product = "s3" if service == "AmazonS3" else "ec2"
    attrs = {
        "servicecode": service,
        "regionCode": "us-east-1",
        "locationType": "AWS Region",
        "operation": "",
        "usagetype": "SYNTHETIC-Storage",
        "storageClass": "General Purpose",
        "volumeType": "Standard",
    }
    family, unit = "Storage", "GB-Mo"
    if product == "ec2":
        family, unit = "Compute Instance", "Hrs"
        attrs = {
            "servicecode": service,
            "regionCode": "us-east-1",
            "locationType": "AWS Region",
            "operation": "RunInstances",
            "usagetype": "SYNTHETIC-BoxUsage",
            "instanceType": "synthetic.xlarge",
            "operatingSystem": "Linux",
            "tenancy": "Shared",
            "preInstalledSw": "NA",
            "capacitystatus": "Used",
            "licenseModel": "No License required",
        }
    entry = SourceRegistryEntry.model_validate(
        {
            "source_id": f"synthetic_{product}_catalog",
            "provider_code": "aws",
            "product_code": product,
            "market_mode": "international",
            "cloud_partition": "aws",
            "source_type": "pricing",
            "title": "SYNTHETIC ONLY",
            "authority_level": "official_primary",
            "url": f"https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{service}/current/us-east-1/index.json",
            "expected_content_type": ["application/json"],
            "domain_policy": {"allowed_domains": ["pricing.us-east-1.amazonaws.com"]},
            "terms_review_status": "approved",
            "automated_fetch_allowed": True,
            "robots_allowed": True,
            "reviewed_at": NOW,
            "robots_checked_at": NOW,
        }
    )
    selection = CatalogSelection(sku=SKU, product_family=family, attributes=attrs.copy(), unit=unit)
    dimensions = {}
    for i, (begin, end, price) in enumerate([("0", "100", "0.1234567890"), ("100", "Inf", "0.10")]):
        rate = f"{TERM}.TEST{i}"
        dimensions[rate] = {
            "rateCode": rate,
            "description": "SYNTHETIC price, not a vendor quote",
            "unit": unit,
            "beginRange": begin,
            "endRange": end,
            "pricePerUnit": {"USD": price},
            "appliesTo": [],
        }
    payload = {
        "formatVersion": "v1.0",
        "offerCode": service,
        "version": "20260929000000",
        "publicationDate": "2026-09-29T00:00:00Z",
        "disclaimer": "SYNTHETIC TEST ONLY",
        "products": {SKU: {"sku": SKU, "productFamily": family, "attributes": attrs}},
        "terms": {
            "OnDemand": {
                SKU: {
                    TERM: {
                        "sku": SKU,
                        "offerTermCode": "JRTCKXETXF",
                        "effectiveDate": "2026-09-01T00:00:00Z",
                        "termAttributes": {},
                        "priceDimensions": dimensions,
                    }
                }
            }
        },
    }
    return entry, payload, selection


def inputs(payload: dict[str, Any], entry: SourceRegistryEntry) -> tuple[bytes, dict[str, Any]]:
    raw = json.dumps(payload).encode()
    manifest = {
        key: getattr(entry, key)
        for key in ("source_id", "provider_code", "market_mode", "product_code", "source_type")
    }
    manifest.update(
        schema_version="1.0",
        requested_url=entry.url,
        final_url=entry.url,
        captured_at="2026-09-29T12:00:00Z",
        http_status=200,
        content_type="application/json",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        content_length_bytes=len(raw),
    )
    return raw, manifest


def inspect(
    entry: SourceRegistryEntry, payload: dict[str, Any], selection: CatalogSelection
) -> dict[str, Any]:
    raw, manifest = inputs(payload, entry)
    return inspect_official_catalog(
        raw, entry=entry, manifest=manifest, selections=[selection], as_of=NOW, max_age_days=7
    )


@pytest.mark.parametrize("service", ["AmazonS3", "AmazonEC2"])
def test_all_tiers_exact_precision_no_implicit_approval(service: str) -> None:
    entry, payload, selection = fixture(service)
    before = copy.deepcopy(payload)
    result = inspect(entry, payload, selection)
    assert result == inspect(entry, payload, selection)
    assert payload == before
    assert len(result["records"]) == 2
    assert result["records"][0]["unit_price"] == "0.1234567890"
    assert result["records"][1]["end_range"] == "Inf"
    assert result["records"][0]["price_locator"].endswith(f"/{TERM}.TEST0")
    assert result["tax_status"] == "unverified"
    assert result["customer_eligible"] is False
    assert result["database_write_performed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("terms_review_status", "pending_review"),
        ("robots_allowed", False),
        ("automated_fetch_allowed", False),
        ("allow_automated_fetch", False),
        ("enabled", False),
        ("manual_only", True),
        ("requires_authentication", True),
        ("requires_browser", True),
        ("provider_code", "aliyun"),
        ("cloud_partition", "aws_cn"),
        ("market_mode", "domestic"),
        ("reviewed_at", None),
        ("robots_checked_at", None),
        (
            "url",
            "https://pricing.us-east-1.amazonaws.com.evil.invalid/offers/v1.0/aws/AmazonS3/current/us-east-1/index.json",
        ),
        (
            "url",
            "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/cn-north-1/index.json",
        ),
    ],
)
def test_unauthorized_sources_fail_closed(field: str, value: Any) -> None:
    entry, payload, selection = fixture()
    with pytest.raises(ValueError):
        inspect(entry.model_copy(update={field: value}), payload, selection)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_sha256", "0" * 64),
        ("content_length_bytes", 1),
        ("source_id", "wrong_source"),
        ("final_url", "https://example.invalid/redirect"),
        ("http_status", 403),
        ("captured_at", "2026-07-01T00:00:00Z"),
        ("captured_at", "2026-10-01T00:00:00Z"),
        ("captured_at", "2026-09-29T12:00:00"),
        ("content_type", "text/html"),
    ],
)
def test_manifest_mismatch_and_stale_capture_block(field: str, value: Any) -> None:
    entry, payload, selection = fixture()
    raw, manifest = inputs(payload, entry)
    manifest[field] = value
    with pytest.raises(ValueError):
        inspect_official_catalog(
            raw, entry=entry, manifest=manifest, selections=[selection], as_of=NOW, max_age_days=7
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("beginRange", "1"),
        ("endRange", "101"),
        ("endRange", "0"),
        ("pricePerUnit", {"USD": "NaN"}),
        ("pricePerUnit", {"USD": "-1"}),
        ("pricePerUnit", {"USD": 0.1}),
        ("pricePerUnit", {"CNY": "1"}),
        ("pricePerUnit", {"USD": "1e100000"}),
        ("unit", "GB-Hour"),
        ("rateCode", "OTHER"),
        ("appliesTo", ["OTHER-SKU"]),
    ],
)
def test_invalid_dimensions_block_entire_selection(field: str, value: Any) -> None:
    entry, payload, selection = fixture()
    payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"][f"{TERM}.TEST0"][field] = value
    with pytest.raises(ValueError):
        inspect(entry, payload, selection)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "sku",
        "region",
        "service",
        "family",
        "offer",
        "effective",
        "publication",
        "format",
        "terminal",
        "attributes",
    ],
)
def test_scope_and_structure_failures(mutation: str) -> None:
    entry, payload, selection = fixture()
    product = payload["products"][SKU]
    offer = payload["terms"]["OnDemand"][SKU][TERM]
    if mutation == "missing":
        del payload["products"][SKU]
    elif mutation == "sku":
        product["sku"] = "OTHER"
    elif mutation == "region":
        product["attributes"]["regionCode"] = "us-west-2"
    elif mutation == "service":
        payload["offerCode"] = "AmazonEC2"
    elif mutation == "family":
        product["productFamily"] = "API Request"
    elif mutation == "offer":
        payload["terms"]["OnDemand"][SKU]["OTHER"] = copy.deepcopy(offer)
    elif mutation == "effective":
        offer["effectiveDate"] = "2026-10-01T00:00:00Z"
    elif mutation == "publication":
        payload["publicationDate"] = "2026-10-01T00:00:00Z"
    elif mutation == "format":
        payload["formatVersion"] = "v2"
    elif mutation == "terminal":
        offer["priceDimensions"][f"{TERM}.TEST1"]["endRange"] = "200"
    elif mutation == "attributes":
        selection = selection.model_copy(update={"attributes": {"regionCode": "us-east-1"}})
    with pytest.raises(ValueError):
        inspect(entry, payload, selection)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"", b"{"])
def test_strict_json(raw: bytes) -> None:
    with pytest.raises(ValueError):
        decode_catalog_json(raw)


def test_size_limit_and_selection_limit() -> None:
    with pytest.raises(ValueError):
        decode_catalog_json(b"{}", limit=1)
    entry, payload, selection = fixture()
    raw, manifest = inputs(payload, entry)
    for selections in ([], [selection, selection], [selection] * 101):
        with pytest.raises(ValueError):
            inspect_official_catalog(
                raw,
                entry=entry,
                manifest=manifest,
                selections=selections,
                as_of=NOW,
                max_age_days=7,
            )


@pytest.mark.parametrize("family,unit", [("API Request", "Requests"), ("Data Transfer", "GB")])
def test_explicit_request_and_transfer_units_preserved(family: str, unit: str) -> None:
    entry, payload, selection = fixture()
    payload["products"][SKU]["productFamily"] = family
    for dimension in payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"].values():
        dimension["unit"] = unit
    selection = selection.model_copy(update={"product_family": family, "unit": unit})
    assert inspect(entry, payload, selection)["records"][0]["unit"] == unit


def test_versioned_url_must_match_content_version() -> None:
    entry, payload, selection = fixture()
    entry = entry.model_copy(update={"url": entry.url.replace("current", payload["version"])})
    assert inspect(entry, payload, selection)["catalog_version"] == payload["version"]
    payload["version"] = "20260928000000"
    with pytest.raises(ValueError):
        inspect(entry, payload, selection)


@pytest.mark.parametrize("service", ["AmazonEC2", "AmazonS3"])
@pytest.mark.parametrize("versioned", [False, True])
def test_documented_api_route_without_robots_is_not_a_fabricated_check(
    service: str, versioned: bool
) -> None:
    entry, payload, selection = fixture(service)
    updates: dict[str, Any] = {"robots_allowed": None, "robots_checked_at": None}
    if versioned:
        updates["url"] = entry.url.replace("current", payload["version"])
    entry = entry.model_copy(update=updates)
    before = entry.model_dump()
    result = inspect(entry, payload, selection)
    policy = result["source_authorization"]
    assert policy["robots_policy"] == "not_applicable_api_route"
    assert policy["recorded_robots_allowed"] is None
    assert policy["recorded_robots_checked_at"] is None
    assert policy["robots_check_performed_by_inspector"] is False
    assert policy["reviewed_at"] == NOW.isoformat()
    assert result["customer_eligible"] is False
    assert entry.model_dump() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("robots_allowed", False),
        ("terms_review_status", "pending"),
        ("automated_fetch_allowed", False),
        ("allow_automated_fetch", False),
        ("reviewed_at", None),
        ("authority_level", "unverified"),
        ("source_type", "documentation"),
        ("url", "https://aws.amazon.com/ec2/pricing/on-demand/"),
        ("url", "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json"),
        (
            "url",
            "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-west-2/index.json",
        ),
        (
            "url",
            "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json?x=1",
        ),
        (
            "url",
            "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.json#x",
        ),
    ],
)
def test_missing_robots_does_not_waive_other_source_guards(field: str, value: Any) -> None:
    entry, payload, selection = fixture("AmazonEC2")
    entry = entry.model_copy(update={"robots_allowed": None, "robots_checked_at": None})
    entry = entry.model_copy(update={field: value})
    with pytest.raises(ValueError):
        inspect(entry, payload, selection)


def test_api_route_policy_does_not_expand_ec2_product_family_scope() -> None:
    entry, payload, selection = fixture("AmazonEC2")
    entry = entry.model_copy(update={"robots_allowed": None, "robots_checked_at": None})
    payload["products"][SKU]["productFamily"] = "Storage"
    selection = selection.model_copy(update={"product_family": "Storage", "unit": "GB-Mo"})
    with pytest.raises(ValueError, match="only explicit EC2 instance-hour scope"):
        inspect(entry, payload, selection)


def test_rate_codes_cannot_forge_json_pointer_paths() -> None:
    entry, payload, selection = fixture()
    dimensions = payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"]
    row = dimensions.pop(f"{TERM}.TEST0")
    forged = f"{TERM}.BAD/path"
    row["rateCode"] = forged
    dimensions[forged] = row
    with pytest.raises(ValueError):
        inspect(entry, payload, selection)


@pytest.mark.parametrize(
    "age,as_of", [(0, NOW), (91, NOW), (True, NOW), (7, NOW.replace(tzinfo=None))]
)
def test_freshness_policy_requires_bounded_days_and_timezone(age: int, as_of: datetime) -> None:
    entry, payload, selection = fixture()
    raw, manifest = inputs(payload, entry)
    with pytest.raises(ValueError):
        inspect_official_catalog(
            raw,
            entry=entry,
            manifest=manifest,
            selections=[selection],
            as_of=as_of,
            max_age_days=age,
        )


@pytest.mark.parametrize("case", ["ok", "unregistered", "escape", "bad_selection"])
def test_cli_read_only_paths(
    case: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import inspect_official_catalog as cli

    entry, payload, selection = fixture()
    raw, manifest = inputs(payload, entry)
    manifest["storage_path"] = "../escape.bin" if case == "escape" else "synthetic.bin"
    selected: Any = {} if case == "bad_selection" else [selection.model_dump()]
    content = {
        "manifest.json": json.dumps(manifest).encode(),
        "selection.json": json.dumps(selected).encode(),
        "synthetic.bin": raw,
    }
    monkeypatch.setattr(cli, "_read", lambda path, limit: content[path.name])
    monkeypatch.setattr(
        cli, "get_entry_by_source_id", lambda _: None if case == "unregistered" else entry
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspect_official_catalog.py",
            "--source-id",
            entry.source_id,
            "--manifest",
            "manifest.json",
            "--selection",
            "selection.json",
            "--as-of",
            NOW.isoformat(),
            "--max-age-days",
            "7",
        ],
    )
    assert cli.main() == (0 if case == "ok" else 1)
    output = json.loads(capsys.readouterr().out)
    assert output["database_write_performed"] is False
    assert output["status"] == ("validated_staging_only" if case == "ok" else "blocked")
