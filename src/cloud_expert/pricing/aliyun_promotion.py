"""Bounded public catalog estimates, never live or customer-approved quotes."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing.aliyun_capture import RULE as CAPTURE_RULE
from cloud_expert.pricing.aliyun_capture import SOURCE_ID, inspect_catalog
from cloud_expert.pricing.extraction import ExtractedPriceRecord, _decode_payload, _hash_text, _utc
from cloud_expert.pricing.supporting_policies import extract_clauses

RULE = "aliyun_bounded_catalog_reference_v1"
TAX_SOURCE = "aliyun_china_billing_tax_policy"


def _verified(
    session: Session, evidence_id: int, source_id: str
) -> tuple[Evidence, SnapshotRecord, str]:
    evidence = session.get(Evidence, evidence_id)
    if evidence is None or evidence.review_status == "rejected":
        raise ValueError("catalog supporting evidence is missing or rejected")
    snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
    entry = get_entry_by_source_id(source_id)
    if snapshot is None or entry is None:
        raise ValueError("catalog supporting source is missing")
    document = snapshot.source_document
    if (
        snapshot.source_id != source_id
        or snapshot.source_document_id != evidence.source_document_id
        or not snapshot.is_current
        or not document.is_current
        or document.content_hash != snapshot.content_hash
        or document.provider.code != "aliyun"
        or document.cloud_partition != "aliyun_public_cn"
        or document.authority_level != "official_primary"
        or document.url != entry.url
        or entry.terms_review_status != "approved"
        or evidence.content_hash != _hash_text(evidence.excerpt)
    ):
        raise ValueError("catalog supporting provenance is invalid")
    return evidence, snapshot, _decode_payload(snapshot)


def _money(value: str, suffix: str = "") -> Decimal:
    match = re.fullmatch(r"￥(\d+(?:\.\d+)?)" + re.escape(suffix), value)
    if match is None:
        raise ValueError("catalog price format is unverified")
    amount = Decimal(match[1])
    if amount != amount.quantize(Decimal("0.00000001")):
        raise ValueError("catalog decimal precision is unsupported")
    return amount


def extract_catalog_record(session: Session, catalog_id: int, tax_id: int) -> ExtractedPriceRecord:
    catalog, snapshot, raw = _verified(session, catalog_id, SOURCE_ID)
    tax, _, tax_raw = _verified(session, tax_id, TAX_SOURCE)
    if json.loads(tax.excerpt) not in extract_clauses(TAX_SOURCE, tax_raw):
        raise ValueError("tax evidence does not prove China-site inclusion")
    captured, records = inspect_catalog(raw.encode())
    row = json.loads(catalog.excerpt)
    if (
        catalog.parser_rule != CAPTURE_RULE
        or row not in records
        or _utc(snapshot.captured_at) != captured
    ):
        raise ValueError("catalog row differs from the immutable browser capture")
    product = session.scalar(
        select(Product)
        .join(Provider)
        .where(
            Provider.code == "aliyun",
            Product.code == "ecs",
            Product.market_mode == "domestic",
        )
    )
    region = session.scalar(
        select(Region)
        .join(Provider)
        .where(
            Provider.code == "aliyun",
            Region.code == "cn-beijing",
        )
    )
    if (
        product is None
        or region is None
        or region.market_mode != "domestic"
        or region.country_code != "CN"
        or region.cloud_partition is None
        or region.cloud_partition.partition_code != "aliyun_public_cn"
    ):
        raise ValueError("domestic ECS product and Beijing partition are required")
    headers, cells = row["headers"], row["cells"]
    assumptions: dict[str, Any]
    if (
        row["section"] == "compute"
        and headers[:7]
        == [
            "实例规格",
            "vCPUs",
            "内存(GiB)",
            "按量目录价",
            "包月目录价",
            "包周价格",
            "按量月价(30天)",
        ]
        and cells[:3] == ["通用型 ecs.g6.xlarge", "4", "16"]
    ):
        # The labeled 30-day amount is authoritative; no unlabeled hourly unit is inferred.
        quantity = Decimal(720)
        unit_price = _money(cells[6]) / quantity
        if unit_price != _money(cells[3]):
            raise ValueError("30-day amount disagrees with the catalog rate")
        code, category, unit, period = "ecs.g6.xlarge:30days", "compute", "instance-hour", "hourly"
        assumptions = {"duration_hours": 720, "duration_origin": "labeled_30_day_catalog_column"}
    elif (
        row["section"] == "disk"
        and row["table_index"] == 0
        and headers[:4]
        == [
            "类别",
            "最大IOPS/最大吞吐量",
            "云盘容量范围（GiB）",
            "按量价格 ( 元/GiB/小时 )",
        ]
        and cells[0] == "ESSD PL1云盘"
        and cells[2] == "20 ~ 65,536 GiB"
    ):
        quantity, unit_price = Decimal(72000), _money(cells[3])
        code, category, unit, period = (
            "essd.pl1:100gib:720h:system",
            "storage",
            "GiB-hour",
            "hourly",
        )
        assumptions = {
            "capacity_gib": 100,
            "duration_hours": 720,
            "usage_origin": "internal_assumption",
        }
    elif (
        row["section"] == "network"
        and headers == ["计费方式", "类型", "价格"]
        and cells[:2]
        == [
            "按使用量线性计费",
            "1GB",
        ]
    ):
        quantity, unit_price = Decimal(100), _money(cells[2], "/GB")
        code, category, unit, period = "ecs.network:100gb", "traffic", "GB", "usage"
        assumptions = {"usage_gb": 100, "usage_origin": "internal_assumption"}
    else:
        raise ValueError("catalog row is outside the bounded reference scope")
    if unit_price != unit_price.quantize(Decimal("0.00000001")):
        raise ValueError("catalog decimal precision is unsupported")
    payload = {
        "scope": "bounded_catalog_reference_only",
        "realtime": False,
        "customer_approved": False,
        "catalog_evidence_id": catalog.id,
        "tax_evidence_id": tax.id,
        "supporting_hashes": {str(e.id): e.content_hash for e in (catalog, tax)},
        "region": "cn-beijing",
        "resource_code": code,
        "assumptions": assumptions,
        "quantity": str(quantity),
        "unit_price": str(unit_price),
        "billing_unit": unit,
        "amount": str(unit_price * quantity),
        "currency": "CNY",
        "tax_included": True,
        "excluded": [
            "live_purchase_quote",
            "availability",
            "personal_discounts",
            "vendor_equivalence",
        ],
    }
    excerpt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return ExtractedPriceRecord(
        provider_code="aliyun",
        product_code="ecs",
        region_code="cn-beijing",
        provider_price_code=f"catalog:cn-beijing:{code}",
        charge_category=category,
        billing_mode="on_demand",
        billing_unit=unit,
        currency="CNY",
        tax_included=True,
        unit_price=unit_price,
        minimum_quantity=quantity,
        maximum_quantity=quantity,
        billing_period=period,
        discount_type="estimated",
        evidence_type="json_path",
        evidence_locator=f"derived:catalog:{catalog.id}:{_hash_text(excerpt)[:16]}",
        evidence_excerpt=excerpt,
        parser_rule=RULE,
        source_payload_path=snapshot.storage_path,
        snapshot_record_id=snapshot.id,
        source_document_id=snapshot.source_document_id,
    )


def catalog_price_valid(session: Session, price: PriceSnapshot) -> bool:
    try:
        evidence = price.evidence
        if evidence.parser_rule != RULE or evidence.review_status == "rejected":
            return False
        data = json.loads(evidence.excerpt)
        expected = extract_catalog_record(
            session, data["catalog_evidence_id"], data["tax_evidence_id"]
        )
        source = session.get(SnapshotRecord, expected.snapshot_record_id)
        sku = price.price_sku
        return bool(
            source is not None
            and evidence.excerpt == expected.evidence_excerpt
            and evidence.content_hash == _hash_text(expected.evidence_excerpt)
            and evidence.source_document_id == expected.source_document_id
            and evidence.snapshot_record_id == source.id
            and _utc(price.captured_at) == _utc(source.captured_at)
            and price.unit_price == expected.unit_price
            and price.minimum_quantity == price.maximum_quantity == expected.minimum_quantity
            and price.billing_period == expected.billing_period
            and price.discount_type == "estimated"
            and price.source_payload_path == expected.source_payload_path
            and sku.provider.code == "aliyun"
            and sku.product.code == "ecs"
            and sku.product.market_mode == "domestic"
            and sku.region.code == "cn-beijing"
            and sku.region.market_mode == "domestic"
            and sku.region.country_code == "CN"
            and sku.region.cloud_partition is not None
            and sku.region.cloud_partition.partition_code == "aliyun_public_cn"
            and sku.region.provider_id == sku.provider_id == sku.product.provider_id
            and sku.provider_price_code == expected.provider_price_code
            and sku.charge_category == expected.charge_category
            and sku.billing_unit == expected.billing_unit
            and sku.billing_mode == "on_demand"
            and sku.currency == "CNY"
            and sku.tax_included is True
        )
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError, IndexError):
        return False
