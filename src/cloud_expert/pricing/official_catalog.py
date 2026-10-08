"""Offline AWS regional OnDemand catalog inspection; no persistence or network I/O."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry

MAX_BYTES = 52_428_800
RULE_VERSION = "aws_regional_catalog_inspection_v2"
HOST = "https://pricing.us-east-1.amazonaws.com"
SERVICES = {"ec2": "AmazonEC2", "s3": "AmazonS3"}


class CatalogSelection(BaseModel):
    """Explicit SKU scope, not a similarity search or a cheapest-price selector."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    sku: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    product_family: str = Field(min_length=1)
    attributes: dict[str, str] = Field(min_length=1)
    unit: str = Field(min_length=1)
    currency: str = "USD"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise ValueError("non-finite JSON constant")


def decode_catalog_json(raw: bytes, *, limit: int = MAX_BYTES) -> Any:
    if not raw or len(raw) > limit:
        raise ValueError("empty or oversized JSON input")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("required JSON object missing")
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO string")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timestamp timezone required")
    return result.astimezone(UTC)


def _number(value: Any) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,24}(?:\.\d{1,18})?", value):
        raise ValueError("price/range must be a bounded nonnegative decimal string")
    return Decimal(value)


def _validate_scope(selection: CatalogSelection, product: dict[str, Any], service: str) -> None:
    attributes = _object(product.get("attributes"))
    required = {"servicecode", "regionCode", "locationType", "usagetype", "operation"}
    if service == "AmazonEC2":
        required |= {
            "instanceType",
            "operatingSystem",
            "tenancy",
            "preInstalledSw",
            "capacitystatus",
            "licenseModel",
        }
        if selection.product_family != "Compute Instance" or selection.unit != "Hrs":
            raise ValueError("only explicit EC2 instance-hour scope is supported")
    elif selection.product_family == "Storage":
        required |= {"storageClass", "volumeType"}
        if selection.unit != "GB-Mo":
            raise ValueError("unsupported storage time unit")
    elif {"API Request": "Requests", "Data Transfer": "GB"}.get(
        selection.product_family
    ) != selection.unit:
        raise ValueError("unsupported S3 product family/unit")
    if (
        not required.issubset(selection.attributes)
        or any(not selection.attributes.get(key) for key in required - {"operation"})
        or selection.attributes.get("servicecode") != service
        or selection.attributes.get("regionCode") != "us-east-1"
        or selection.attributes.get("locationType") != "AWS Region"
        or selection.currency != "USD"
        or selection.unit not in {"Hrs", "GB-Mo", "GB", "Requests"}
        or product.get("sku") != selection.sku
        or product.get("productFamily") != selection.product_family
        or any(not isinstance(value, str) for value in attributes.values())
        or any(attributes.get(key) != value for key, value in selection.attributes.items())
    ):
        raise ValueError("SKU, service, region, attributes or unit scope mismatch")


def _tiers(
    selection: CatalogSelection, offers: dict[str, Any], as_of: datetime
) -> list[dict[str, Any]]:
    if len(offers) != 1:
        raise ValueError("exactly one unambiguous OnDemand offer is required")
    offer_key, offer = next(iter(offers.items()))
    offer = _object(offer)
    code = offer.get("offerTermCode")
    if (
        not isinstance(code, str)
        or not re.fullmatch(r"[A-Z0-9]+", code)
        or offer_key != f"{selection.sku}.{code}"
        or offer.get("sku") != selection.sku
        or offer.get("termAttributes") != {}
        or _time(offer.get("effectiveDate")) > as_of
    ):
        raise ValueError("offer identity, conditions or effective date invalid")
    dimensions = _object(offer.get("priceDimensions"))
    if not 1 <= len(dimensions) <= 1000:
        raise ValueError("missing or excessive price dimensions")
    rows: list[dict[str, Any]] = []
    for rate_code, value in dimensions.items():
        dimension = _object(value)
        if (
            not re.fullmatch(re.escape(offer_key) + r"\.[A-Z0-9]+", rate_code)
            or dimension.get("rateCode") != rate_code
            or dimension.get("unit") != selection.unit
            or dimension.get("appliesTo") != []
            or not isinstance(dimension.get("description"), str)
            or not dimension["description"].strip()
        ):
            raise ValueError("rate identity, unit or applicability invalid")
        prices = _object(dimension.get("pricePerUnit"))
        if set(prices) != {selection.currency}:
            raise ValueError("unexpected price currency")
        _number(prices[selection.currency])
        begin = _number(dimension.get("beginRange"))
        end = dimension.get("endRange")
        if end != "Inf" and _number(end) <= begin:
            raise ValueError("non-increasing tier")
        rows.append(
            {
                "sku": selection.sku,
                "rate_code": rate_code,
                "effective_from": offer["effectiveDate"],
                "effective_to": None,
                "unit": selection.unit,
                "currency": selection.currency,
                "unit_price": prices[selection.currency],
                "begin_range": dimension["beginRange"],
                "end_range": end,
                "description": dimension["description"],
                "product_locator": f"/products/{selection.sku}",
                "price_locator": f"/terms/OnDemand/{selection.sku}/{offer_key}/priceDimensions/{rate_code}",
            }
        )
    rows.sort(key=lambda row: _number(row["begin_range"]))
    expected: Decimal | None = Decimal(0)
    for row in rows:
        if expected is None or _number(row["begin_range"]) != expected:
            raise ValueError("tier overlap or gap")
        expected = None if row["end_range"] == "Inf" else _number(row["end_range"])
    if expected is not None:
        raise ValueError("incomplete terminal tier")
    return rows


def validate_official_catalog_source(entry: SourceRegistryEntry) -> dict[str, Any]:
    """Authorize only exact documented Bulk API routes, never arbitrary AWS pages.

    A missing robots observation is not a fabricated successful robots check.
    Explicit denial remains binding even on a documented API route.
    """
    service = SERVICES.get(entry.product_code or "")
    if (
        entry.provider_code != "aws"
        or service is None
        or entry.market_mode != "international"
        or entry.cloud_partition != "aws"
        or entry.source_type != "pricing"
        or entry.authority_level != "official_primary"
        or entry.terms_review_status != "approved"
        or entry.robots_allowed is False
        or entry.reviewed_at is None
        or (entry.robots_allowed is True and entry.robots_checked_at is None)
        or not entry.enabled
        or not entry.allow_automated_fetch
        or entry.automated_fetch_allowed is not True
        or entry.manual_only
        or entry.requires_authentication
        or entry.requires_browser
    ):
        raise ValueError("source is not authorized public AWS catalog input")
    url_pattern = (
        re.escape(f"{HOST}/offers/v1.0/aws/{service}/") + r"(current|\d{14})/us-east-1/index\.json"
    )
    url_match = re.fullmatch(url_pattern, entry.url)
    if url_match is None:
        raise ValueError("unsupported official regional catalog URL")
    return {
        "basis": "registered_terms_approved_documented_bulk_api_route",
        "documentation_url": "https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api-fetching-price-list-files-manually.html",
        "service_code": service,
        "catalog_url_version": url_match[1],
        "terms_review_status": entry.terms_review_status,
        "automated_fetch_allowed": entry.automated_fetch_allowed,
        "reviewed_at": entry.reviewed_at.isoformat(),
        "robots_policy": (
            "not_applicable_api_route" if entry.robots_allowed is None else "recorded_allow"
        ),
        "recorded_robots_allowed": entry.robots_allowed,
        "recorded_robots_checked_at": (
            entry.robots_checked_at.isoformat() if entry.robots_checked_at else None
        ),
        "robots_check_performed_by_inspector": False,
    }


def inspect_official_catalog(
    raw: bytes,
    *,
    entry: SourceRegistryEntry,
    manifest: dict[str, Any],
    selections: list[CatalogSelection],
    as_of: datetime,
    max_age_days: int,
) -> dict[str, Any]:
    """Return staged evidence candidates only; unknown tax never becomes tax-excluded."""
    if type(max_age_days) is not int or not 1 <= max_age_days <= 90:
        raise ValueError("explicit aware as_of and bounded freshness policy required")
    return _inspect_catalog(
        raw,
        entry=entry,
        manifest=manifest,
        selections=selections,
        as_of=as_of,
        max_age_days=max_age_days,
    )


def inspect_official_catalog_facts(
    raw: bytes,
    *,
    entry: SourceRegistryEntry,
    manifest: dict[str, Any],
    selections: list[CatalogSelection],
    checked_at: datetime,
) -> dict[str, Any]:
    """Archived facts only. Does not assert freshness or authorize consumption."""
    return _inspect_catalog(
        raw,
        entry=entry,
        manifest=manifest,
        selections=selections,
        as_of=checked_at,
        max_age_days=None,
    )


def _inspect_catalog(
    raw: bytes,
    *,
    entry: SourceRegistryEntry,
    manifest: dict[str, Any],
    selections: list[CatalogSelection],
    as_of: datetime,
    max_age_days: int | None,
) -> dict[str, Any]:
    authorization = validate_official_catalog_source(entry)
    service = authorization["service_code"]
    if as_of.tzinfo is None:
        raise ValueError("explicit aware as_of and bounded freshness policy required")
    captured = _time(manifest.get("captured_at"))
    if captured > as_of or (
        max_age_days is not None and as_of - captured > timedelta(days=max_age_days)
    ):
        raise ValueError("snapshot is stale or captured in the future")
    digest = hashlib.sha256(raw).hexdigest()
    if (
        manifest.get("schema_version") != "1.0"
        or any(
            manifest.get(key) != getattr(entry, key)
            for key in ("source_id", "provider_code", "market_mode", "product_code", "source_type")
        )
        or manifest.get("requested_url") != entry.url
        or manifest.get("final_url") != entry.url
        or manifest.get("http_status") != 200
        or manifest.get("content_type") not in {"application/json", "application/octet-stream"}
        or manifest.get("content_type") not in entry.expected_content_type
        or manifest.get("content_sha256") != digest
        or manifest.get("content_length_bytes") != len(raw)
    ):
        raise ValueError("snapshot manifest provenance/integrity mismatch")
    payload = _object(
        decode_catalog_json(raw, limit=min(MAX_BYTES, entry.fetch_policy.max_content_length_bytes))
    )
    version = payload.get("version")
    if (
        payload.get("formatVersion") != "v1.0"
        or payload.get("offerCode") != service
        or not isinstance(version, str)
        or not re.fullmatch(r"\d{14}", version)
        or authorization["catalog_url_version"] not in {"current", version}
        or _time(payload.get("publicationDate")) > captured
        or not isinstance(payload.get("disclaimer"), str)
        or not payload["disclaimer"].strip()
    ):
        raise ValueError("catalog format, version, service or publication invalid")
    if not 1 <= len(selections) <= 100 or len({s.sku for s in selections}) != len(selections):
        raise ValueError("one to 100 unique explicit SKU selections required")
    products = _object(payload.get("products"))
    on_demand = _object(_object(payload.get("terms")).get("OnDemand"))
    records = []
    for selection in sorted(selections, key=lambda s: s.sku):
        product = _object(products.get(selection.sku))
        _validate_scope(selection, product, service)
        for row in _tiers(selection, _object(on_demand.get(selection.sku)), as_of):
            row["product_attributes"] = product["attributes"]
            row["product_family"] = product["productFamily"]
            records.append(row)
    return {
        "rule_version": RULE_VERSION,
        "status": "verified_archived_facts_only"
        if max_age_days is None
        else "validated_staging_only",
        "source_id": entry.source_id,
        "source_url": entry.url,
        "source_authorization": authorization,
        "raw_sha256": digest,
        "catalog_version": version,
        "publication_date": payload["publicationDate"],
        "captured_at": manifest["captured_at"],
        "as_of": as_of.isoformat(),
        "max_age_days": max_age_days,
        "disclaimer": payload["disclaimer"],
        "market_mode": "international",
        "cloud_partition": "aws",
        "region": "us-east-1",
        "price_basis": "public_catalog",
        "tax_status": "unverified",
        "customer_eligible": False,
        "database_write_performed": False,
        "records": records,
        "required_before_promotion": [
            "SourceDocument/SnapshotRecord/Evidence linkage and independent scope review",
            "official tax and quantity/time unit policy evidence",
            "scenario-specific component coverage and freshness revalidation",
        ],
    }
