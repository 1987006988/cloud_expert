"""Promote bounded official quotes with independently verified unit and tax evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.config.settings import get_settings
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing.api_capture import _validate_quote_scope
from cloud_expert.pricing.huawei_api import PricingQuery, ProductQuery, validate_response
from cloud_expert.pricing.supporting_policies import extract_clauses

TAX_SOURCE = "huawei_cloud_billing_tax_policy"
TAX_SENTENCE = "\u534e\u4e3a\u4e91\u4e91\u670d\u52a1\u5546\u54c1\u5b9a\u4ef7\u5305\u542b\u7a0e\u4ef7\uff0c\u6545\u8d26\u5355\u4e2d\u7684\u91d1\u989d\u662f\u542b\u7a0e\u7684\u3002"
RULE = "huawei_bounded_official_quote_v1"
UNIT_SCOPE = {
    "Duration": (4, "h", 2, "instance-hour", Decimal(1), "compute", "hourly"),
    "get": (54, "TTM", 4, "request", Decimal(10000), "request", "usage"),
    "put": (54, "TTM", 4, "request", Decimal(10000), "request", "usage"),
    "download.external": (10, "G", 3, "GB", Decimal(1), "traffic", "usage"),
    "upflow": (10, "G", 3, "GB", Decimal(1), "traffic", "usage"),
}


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _raw(session: Session, snapshot: SnapshotRecord, root: Path) -> bytes:
    document = snapshot.source_document
    entry = get_entry_by_source_id(snapshot.source_id)
    path = (root / snapshot.storage_path).resolve()
    if (
        entry is None
        or entry.terms_review_status != "approved"
        or not snapshot.is_current
        or not document.is_current
        or document.cloud_partition != "huawei_cn"
        or document.provider.code != entry.provider_code
        or document.authority_level != "official_primary"
        or document.url != entry.url
        or document.content_hash != snapshot.content_hash
        or not path.is_relative_to(root)
    ):
        raise ValueError("price supporting snapshot is not current, approved or in scope")
    raw = path.read_bytes()
    if _digest(raw) != snapshot.content_hash:
        raise ValueError("supporting raw snapshot hash mismatch")
    return raw


def _evidence(
    session: Session, evidence_id: int, root: Path
) -> tuple[Evidence, SnapshotRecord, bytes]:
    evidence = session.get(Evidence, evidence_id)
    if evidence is None or evidence.review_status == "rejected" or not evidence.snapshot_record_id:
        raise ValueError("supporting evidence is missing or rejected")
    snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
    if snapshot is None or snapshot.source_document_id != evidence.source_document_id:
        raise ValueError("supporting evidence snapshot link is invalid")
    raw = _raw(session, snapshot, root)
    if evidence.content_hash != _digest(evidence.excerpt.encode()):
        raise ValueError("supporting evidence excerpt hash mismatch")
    return evidence, snapshot, raw


def _get_or_create_evidence(
    session: Session, snapshot: SnapshotRecord, locator: str, excerpt: str, rule: str
) -> Evidence:
    row = session.scalar(
        select(Evidence).where(
            Evidence.snapshot_record_id == snapshot.id,
            Evidence.locator == locator,
            Evidence.parser_rule == rule,
        )
    )
    if row is not None:
        if row.excerpt != excerpt or row.content_hash != _digest(excerpt.encode()):
            raise ValueError("existing immutable evidence differs")
        return row
    row = Evidence(
        source_document_id=snapshot.source_document_id,
        snapshot_record_id=snapshot.id,
        locator=locator,
        excerpt=excerpt,
        content_hash=_digest(excerpt.encode()),
        evidence_type="json_path" if rule == RULE else "html_section",
        parser_rule=rule,
        confidence=1.0,
        review_status="machine_extracted",
    )
    session.add(row)
    session.flush()
    return row


def extract_tax_policy(session: Session, *, root: Path | None = None) -> Evidence:
    root = (root or Path(get_settings().raw_data_dir)).resolve()
    snapshot = session.scalar(
        select(SnapshotRecord).where(
            SnapshotRecord.source_id == TAX_SOURCE,
            SnapshotRecord.is_current.is_(True),
        )
    )
    if snapshot is None:
        raise ValueError("official tax policy snapshot is missing")
    text = BeautifulSoup(_raw(session, snapshot, root), "html.parser").get_text(" ", strip=True)
    if TAX_SENTENCE not in text:
        raise ValueError("official domestic tax inclusion statement not found")
    return _get_or_create_evidence(
        session,
        snapshot,
        "text:domestic-cloud-service-tax-inclusion",
        TAX_SENTENCE,
        "huawei_cn_tax_policy_v1",
    )


def _component_scope(
    session: Session, item: ProductQuery, size_evidence_id: int | None, root: Path
) -> tuple[tuple[int, str, int, str, Decimal, str, str], Evidence | None]:
    scope = UNIT_SCOPE.get(item.usage_factor)
    if scope is None:
        raise ValueError("unsupported or unverified billing period; storage remains quarantined")
    disk = item.usage_factor == "Duration" and item.resource_type == "hws.resource.type.volume"
    traffic = item.usage_factor == "upflow"
    if (
        item.usage_factor == "Duration"
        and not disk
        and item.resource_type != "hws.resource.type.vm"
    ):
        raise ValueError("non-VM duration requires a component-specific price promotion rule")
    if not disk and not traffic:
        if size_evidence_id is not None:
            raise ValueError("unexpected component size evidence")
        return scope, None
    if size_evidence_id is None:
        raise ValueError("component size unit requires official evidence")
    size, snapshot, raw = _evidence(session, size_evidence_id, root)
    source_id = "huawei_cloud_pricing_api_parameters"
    expected_unit = 17 if disk else 15
    clauses = extract_clauses(source_id, raw.decode("utf-8"))
    expected_clause = clauses[1 if disk else 0]
    if (
        snapshot.source_id != source_id
        or json.loads(size.excerpt) != expected_clause
        or item.size_measure_id != expected_unit
        or item.resource_size is None
        or item.resource_size <= 0
    ):
        raise ValueError("component size evidence does not match the quote")
    if disk:
        scope = (4, "h", 2, "GB-hour", Decimal(str(item.resource_size)), "storage", "hourly")
    return scope, size


def promote_quote(
    session: Session,
    quote_evidence_id: int,
    unit_evidence_id: int,
    tax_evidence_id: int,
    *,
    size_evidence_id: int | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = (root or Path(get_settings().raw_data_dir)).resolve()
    quote, snapshot, raw = _evidence(session, quote_evidence_id, root)
    unit, unit_snapshot, unit_raw = _evidence(session, unit_evidence_id, root)
    tax, tax_snapshot, tax_raw = _evidence(session, tax_evidence_id, root)
    if (
        quote.parser_rule != "huawei_api_ui_copy_v1"
        or unit_snapshot.source_id != "huawei_cloud_billing_measurements_api"
    ):
        raise ValueError("unsupported quote/unit evidence parser")
    if (
        tax_snapshot.source_id != TAX_SOURCE
        or tax.excerpt != TAX_SENTENCE
        or TAX_SENTENCE not in BeautifulSoup(tax_raw, "html.parser").get_text(" ", strip=True)
    ):
        raise ValueError("tax evidence does not prove domestic inclusion")
    manifest_path = (root / snapshot.manifest_path).resolve()
    if not manifest_path.is_relative_to(root):
        raise ValueError("quote manifest path escapes raw storage")
    manifest = SnapshotStore(root).load_manifest(manifest_path)
    if manifest.content_sha256 != snapshot.content_hash:
        raise ValueError("quote manifest hash mismatch")
    query = PricingQuery.model_validate(manifest.content_metadata["request"])
    entry = get_entry_by_source_id(snapshot.source_id)
    assert entry is not None
    _validate_quote_scope(entry, query)
    validate_response(raw, query)
    excerpt = json.loads(quote.excerpt)
    item = next(
        (
            item
            for item in query.product_infos
            if item.model_dump(exclude_none=True) == excerpt.get("request")
        ),
        None,
    )
    if item is None:
        raise ValueError("unsupported or unverified billing period; storage remains quarantined")
    scope, size = _component_scope(session, item, size_evidence_id, root)
    response = json.loads(raw, parse_float=Decimal)
    row = next(row for row in response["product_rating_results"] if row["id"] == item.id)
    amount = Decimal(str(row["official_website_amount"]))
    if response.get("currency") != "CNY" or amount != Decimal(
        str(excerpt["official_website_amount"])
    ):
        raise ValueError("quoted amount/currency differs from raw response")
    mid, abbreviation, kind, billing_unit, multiplier, category, period = scope
    definition = json.loads(unit.excerpt)
    if (
        item.usage_measure_id != mid
        or definition.get("measure_id") != mid
        or definition.get("abbreviation") != abbreviation
        or definition.get("measure_type") != kind
        or definition not in json.loads(unit_raw).get("measure_units", [])
    ):
        raise ValueError("official unit evidence does not match query")
    quantity = Decimal(str(item.usage_value)) * multiplier
    unit_price = amount / quantity
    if unit_price != unit_price.quantize(Decimal("0.00000001")):
        raise ValueError("price exceeds supported decimal precision")
    provider_id = snapshot.source_document.provider_id
    product = session.scalar(
        select(Product).where(
            Product.provider_id == provider_id,
            Product.code == entry.product_code,
            Product.market_mode == "domestic",
        )
    )
    partition = session.scalar(
        select(CloudPartition).where(
            CloudPartition.provider_id == provider_id, CloudPartition.partition_code == "huawei_cn"
        )
    )
    if product is None or partition is None:
        raise ValueError("domestic product or partition is missing")
    region = session.scalar(
        select(Region).where(Region.provider_id == provider_id, Region.code == item.region)
    )
    if region is None:
        region = Region(
            provider_id=provider_id,
            cloud_partition_id=partition.id,
            code=item.region,
            name=item.region,
            country_code="CN",
            market_mode="domestic",
        )
        session.add(region)
        session.flush()
    if (
        region.market_mode != "domestic"
        or region.cloud_partition_id != partition.id
        or region.country_code != "CN"
    ):
        raise ValueError("region market or partition mismatch")
    # The source provides a quoted quantity, not a tariff valid for arbitrary usage.
    payload: dict[str, Any] = {
        "scope": "exact_quoted_quantity_only",
        "resource_spec": item.resource_spec,
        "usage_factor": item.usage_factor,
        "region": item.region,
        "tax_included": True,
        "tax_jurisdiction": "huawei_cn",
        "tax_rate": None,
        "quote_evidence_id": quote.id,
        "unit_evidence_id": unit.id,
        "tax_evidence_id": tax.id,
        "official_amount": str(amount),
        "quantity": str(quantity),
        "unit_price": str(unit_price),
        "billing_unit": billing_unit,
        "billing_period": period,
        "currency": "CNY",
        "customer_approved": False,
        "supporting_hashes": {str(e.id): e.content_hash for e in (quote, unit, tax)},
    }
    if size is not None:
        payload["size_evidence_id"] = size.id
        payload["component_request"] = item.model_dump(exclude_none=True)
        payload["supporting_hashes"][str(size.id)] = size.content_hash
    serialized = json.dumps(payload, sort_keys=True)
    derived = _get_or_create_evidence(
        session,
        snapshot,
        f"derived:bounded_quote:{quote.id}:{_digest(serialized.encode())[:16]}",
        serialized,
        RULE,
    )
    code = f"api:{entry.product_code}:{item.region}:{item.resource_spec}:{item.usage_factor}:{quantity}"
    if size is not None:
        code += f":size{item.resource_size}:unit{item.size_measure_id}"
    price_sku = session.scalar(
        select(PriceSKU).where(
            PriceSKU.provider_id == provider_id, PriceSKU.provider_price_code == code
        )
    )
    fields = {
        "provider_id": provider_id,
        "product_id": product.id,
        "region_id": region.id,
        "charge_category": category,
        "billing_mode": "on_demand",
        "billing_unit": billing_unit,
        "currency": "CNY",
        "tax_included": True,
    }
    if price_sku is None:
        price_sku = PriceSKU(provider_price_code=code, **fields)
        session.add(price_sku)
        session.flush()
    elif any(getattr(price_sku, key) != value for key, value in fields.items()):
        raise ValueError("existing price SKU conflicts with immutable quote scope")
    price = session.scalar(
        select(PriceSnapshot).where(
            PriceSnapshot.price_sku_id == price_sku.id, PriceSnapshot.evidence_id == derived.id
        )
    )
    created = price is None
    if price is None:
        price = PriceSnapshot(
            price_sku_id=price_sku.id,
            unit_price=unit_price,
            minimum_quantity=quantity,
            maximum_quantity=quantity,
            billing_period=period,
            discount_type="list",
            captured_at=snapshot.captured_at,
            evidence_id=derived.id,
            source_payload_path=snapshot.storage_path,
        )
        session.add(price)
        session.flush()
    elif (
        price.unit_price != unit_price
        or price.minimum_quantity != quantity
        or price.maximum_quantity != quantity
        or price.billing_period != period
        or price.discount_type != "list"
        or price.source_payload_path != snapshot.storage_path
        or _utc(price.captured_at) != _utc(snapshot.captured_at)
    ):
        raise ValueError("existing price snapshot differs from bounded quote")
    return {
        "price_sku_id": price_sku.id,
        "price_snapshot_id": price.id,
        "evidence_id": derived.id,
        "created": created,
        "quantity": str(quantity),
        "billing_unit": billing_unit,
        "customer_approved": False,
    }


def bounded_quote_valid(
    session: Session, price: PriceSnapshot, *, root: Path | None = None
) -> bool:
    """Recheck supporting evidence at consumption, not only on the import date."""
    root = (root or Path(get_settings().raw_data_dir)).resolve()
    try:
        derived, snapshot, _ = _evidence(session, price.evidence_id, root)
        if derived.parser_rule != RULE:
            return False
        data = json.loads(derived.excerpt)
        quote, quote_snapshot, quote_raw = _evidence(session, data["quote_evidence_id"], root)
        unit, unit_snapshot, unit_raw = _evidence(session, data["unit_evidence_id"], root)
        tax, tax_snapshot, tax_raw = _evidence(session, data["tax_evidence_id"], root)
        if snapshot.id != quote_snapshot.id or tax_snapshot.source_id != TAX_SOURCE:
            return False
        if tax.excerpt != TAX_SENTENCE or TAX_SENTENCE not in BeautifulSoup(
            tax_raw, "html.parser"
        ).get_text(" ", strip=True):
            return False
        if unit_snapshot.source_id != "huawei_cloud_billing_measurements_api":
            return False
        definition = json.loads(unit.excerpt)
        query_row = json.loads(quote.excerpt)["request"]
        scope, size = _component_scope(
            session, ProductQuery.model_validate(query_row), data.get("size_evidence_id"), root
        )
        mid, abbreviation, kind, billing_unit, multiplier, category, period = scope
        support = [quote, unit, tax] + ([size] if size is not None else [])
        if data["supporting_hashes"] != {str(e.id): e.content_hash for e in support}:
            return False
        if size is not None and data.get("component_request") != query_row:
            return False
        manifest_path = (root / snapshot.manifest_path).resolve()
        if not manifest_path.is_relative_to(root):
            return False
        manifest = SnapshotStore(root).load_manifest(manifest_path)
        if manifest.content_sha256 != snapshot.content_hash:
            return False
        query = PricingQuery.model_validate(manifest.content_metadata["request"])
        entry = get_entry_by_source_id(snapshot.source_id)
        if entry is None:
            return False
        _validate_quote_scope(entry, query)
        validate_response(quote_raw, query)
        if query_row not in [item.model_dump(exclude_none=True) for item in query.product_infos]:
            return False
        response = json.loads(quote_raw, parse_float=Decimal)
        row = next(
            row for row in response["product_rating_results"] if row["id"] == query_row["id"]
        )
        quantity = Decimal(str(query_row["usage_value"])) * multiplier
        sku = price.price_sku
        return bool(
            definition in json.loads(unit_raw)["measure_units"]
            and (definition["measure_id"], definition["abbreviation"], definition["measure_type"])
            == (mid, abbreviation, kind)
            and query_row["usage_measure_id"] == mid
            and query_row["resource_spec"] == data["resource_spec"]
            and query_row["usage_factor"] == data["usage_factor"]
            and query_row["region"] == data["region"] == sku.region.code
            and sku.region.market_mode == "domestic"
            and sku.region.country_code == "CN"
            and sku.region.cloud_partition is not None
            and sku.region.cloud_partition.partition_code == "huawei_cn"
            and sku.region.provider_id == sku.provider_id == sku.product.provider_id
            and sku.product.market_mode == "domestic"
            and sku.product.code == entry.product_code
            and sku.billing_mode == "on_demand"
            and sku.provider_id == snapshot.source_document.provider_id
            and sku.currency == response["currency"] == data["currency"] == "CNY"
            and sku.billing_unit == data["billing_unit"] == billing_unit
            and sku.charge_category == category
            and sku.tax_included is True
            and data["tax_included"] is True
            and price.unit_price == Decimal(data["unit_price"])
            and price.unit_price * quantity
            == Decimal(str(row["official_website_amount"]))
            == Decimal(data["official_amount"])
            and price.minimum_quantity
            == price.maximum_quantity
            == quantity
            == Decimal(data["quantity"])
            and price.billing_period == data["billing_period"] == period
            and price.source_payload_path == snapshot.storage_path
            and price.discount_type == "list"
            and _utc(price.captured_at) == _utc(snapshot.captured_at)
            and _utc(manifest.captured_at) == _utc(snapshot.captured_at)
            and data["scope"] == "exact_quoted_quantity_only"
            and data["customer_approved"] is False
        )
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError, StopIteration):
        return False
