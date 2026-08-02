from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.config.settings import get_settings
from cloud_expert.database.enums import (
    BillingMode,
    ChargeCategory,
    DiscountType,
    EvidenceType,
    ReviewStatus,
    SourceType,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument

AWS_S3_STANDARD_SOURCE_ID = "aws_s3_pricing_bulk_us_east_1"


@dataclass(frozen=True)
class ExtractedPriceRecord:
    provider_code: str
    product_code: str
    region_code: str
    provider_price_code: str
    charge_category: str
    billing_mode: str
    billing_unit: str
    currency: str
    tax_included: bool
    unit_price: Decimal
    minimum_quantity: Decimal | None
    maximum_quantity: Decimal | None
    billing_period: str
    discount_type: str
    evidence_type: str
    evidence_locator: str
    evidence_excerpt: str
    parser_rule: str
    source_payload_path: str
    snapshot_record_id: int
    source_document_id: int


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raw_data_dir() -> Path:
    return Path(get_settings().raw_data_dir).resolve()


def _snapshot_payload_path(snapshot: SnapshotRecord) -> Path:
    return _raw_data_dir() / snapshot.storage_path


def _decode_payload(snapshot: SnapshotRecord) -> str:
    raw = _snapshot_payload_path(snapshot).read_bytes()
    return raw.decode("utf-8", errors="replace")


def _html_excerpt(payload: str, *, limit: int = 360) -> str:
    text = BeautifulSoup(payload, "html.parser").get_text(" ", strip=True)
    return text[:limit] if text else "Official pricing source snapshot captured."


def current_pricing_snapshots(session: Session) -> list[tuple[SnapshotRecord, SourceDocument]]:
    rows = session.execute(
        select(SnapshotRecord, SourceDocument)
        .join(SourceDocument, SnapshotRecord.source_document_id == SourceDocument.id)
        .where(
            SourceDocument.source_type == SourceType.PRICING.value,
            SnapshotRecord.is_current.is_(True),
        )
        .order_by(SnapshotRecord.source_id, SnapshotRecord.captured_at.desc())
    ).all()
    return [(snapshot, document) for snapshot, document in rows]


def ensure_snapshot_evidence(
    session: Session,
    snapshot: SnapshotRecord,
    document: SourceDocument,
) -> Evidence:
    locator = f"snapshot:{snapshot.source_id}:{snapshot.content_hash}"
    evidence = session.scalar(
        select(Evidence).where(
            Evidence.source_document_id == document.id,
            Evidence.snapshot_record_id == snapshot.id,
            Evidence.locator == locator,
            Evidence.parser_rule == "pricing_source_snapshot_manifest",
        )
    )
    if evidence is not None:
        return evidence

    payload = _decode_payload(snapshot)
    excerpt = _html_excerpt(payload) if snapshot.content_type == "text/html" else document.title
    evidence = Evidence(
        source_document_id=document.id,
        section_title="Official pricing source snapshot",
        page_title=document.title,
        locator=locator,
        excerpt=excerpt,
        evidence_type=(
            EvidenceType.HTML_SECTION.value
            if snapshot.content_type == "text/html"
            else EvidenceType.JSON_PATH.value
        ),
        snapshot_record_id=snapshot.id,
        content_hash=_hash_text(excerpt),
        parser_rule="pricing_source_snapshot_manifest",
        confidence=1.0,
        review_status=ReviewStatus.MACHINE_EXTRACTED.value,
    )
    session.add(evidence)
    session.flush()
    return evidence


def extract_price_records(session: Session) -> list[ExtractedPriceRecord]:
    records: list[ExtractedPriceRecord] = []
    for snapshot, document in current_pricing_snapshots(session):
        ensure_snapshot_evidence(session, snapshot, document)
        if snapshot.source_id == AWS_S3_STANDARD_SOURCE_ID:
            records.extend(_extract_aws_s3_standard_storage(snapshot, document))
    return records


def persist_price_records(
    session: Session,
    records: list[ExtractedPriceRecord],
) -> dict[str, Any]:
    created_skus = 0
    created_snapshots = 0
    skipped_records: list[dict[str, str]] = []
    for record in records:
        provider = session.scalar(select(Provider).where(Provider.code == record.provider_code))
        if provider is None:
            skipped_records.append({"provider": record.provider_code, "reason": "missing provider"})
            continue
        product = session.scalar(
            select(Product).where(
                Product.provider_id == provider.id,
                Product.code == record.product_code,
            )
        )
        if product is None:
            skipped_records.append(
                {
                    "product": f"{record.provider_code}/{record.product_code}",
                    "reason": "missing product",
                }
            )
            continue
        region = session.scalar(
            select(Region).where(
                Region.provider_id == provider.id,
                Region.code == record.region_code,
            )
        )
        if region is None:
            skipped_records.append(
                {
                    "region": f"{record.provider_code}/{record.region_code}",
                    "reason": "missing region",
                }
            )
            continue

        evidence = _ensure_price_evidence(session, record)
        price_sku = session.scalar(
            select(PriceSKU).where(
                PriceSKU.provider_id == provider.id,
                PriceSKU.provider_price_code == record.provider_price_code,
            )
        )
        if price_sku is None:
            price_sku = PriceSKU(
                provider_id=provider.id,
                product_id=product.id,
                sku_id=None,
                region_id=region.id,
                provider_price_code=record.provider_price_code,
                charge_category=record.charge_category,
                billing_mode=record.billing_mode,
                billing_unit=record.billing_unit,
                currency=record.currency,
                tax_included=record.tax_included,
            )
            session.add(price_sku)
            session.flush()
            created_skus += 1

        existing_snapshot = session.scalar(
            select(PriceSnapshot).where(
                PriceSnapshot.price_sku_id == price_sku.id,
                PriceSnapshot.unit_price == record.unit_price,
                PriceSnapshot.evidence_id == evidence.id,
                PriceSnapshot.source_payload_path == record.source_payload_path,
            )
        )
        if existing_snapshot is None:
            session.add(
                PriceSnapshot(
                    price_sku_id=price_sku.id,
                    unit_price=record.unit_price,
                    minimum_quantity=record.minimum_quantity,
                    maximum_quantity=record.maximum_quantity,
                    billing_period=record.billing_period,
                    discount_type=record.discount_type,
                    evidence_id=evidence.id,
                    source_payload_path=record.source_payload_path,
                )
            )
            session.flush()
            created_snapshots += 1
    session.commit()
    return {
        "extracted_records": len(records),
        "created_price_skus": created_skus,
        "created_price_snapshots": created_snapshots,
        "skipped_records": skipped_records,
    }


def _ensure_price_evidence(session: Session, record: ExtractedPriceRecord) -> Evidence:
    evidence = session.scalar(
        select(Evidence).where(
            Evidence.source_document_id == record.source_document_id,
            Evidence.snapshot_record_id == record.snapshot_record_id,
            Evidence.locator == record.evidence_locator,
            Evidence.parser_rule == record.parser_rule,
        )
    )
    if evidence is not None:
        return evidence
    evidence = Evidence(
        source_document_id=record.source_document_id,
        section_title="Official price record",
        page_title=f"{record.provider_code}/{record.product_code}",
        locator=record.evidence_locator,
        excerpt=record.evidence_excerpt,
        evidence_type=record.evidence_type,
        snapshot_record_id=record.snapshot_record_id,
        content_hash=_hash_text(record.evidence_excerpt),
        parser_rule=record.parser_rule,
        confidence=1.0,
        review_status=ReviewStatus.MACHINE_EXTRACTED.value,
    )
    session.add(evidence)
    session.flush()
    return evidence


def _extract_aws_s3_standard_storage(
    snapshot: SnapshotRecord,
    document: SourceDocument,
) -> list[ExtractedPriceRecord]:
    payload = json.loads(_decode_payload(snapshot))
    products = payload.get("products", {})
    terms = payload.get("terms", {}).get("OnDemand", {})
    if not isinstance(products, dict) or not isinstance(terms, dict):
        return []

    records: list[ExtractedPriceRecord] = []
    for sku, product in products.items():
        if not isinstance(product, dict):
            continue
        attributes = product.get("attributes", {})
        if not isinstance(attributes, dict):
            continue
        if not _is_aws_s3_standard_storage_product(product, attributes):
            continue
        term = terms.get(sku)
        if not isinstance(term, dict):
            continue
        for offer_term_code, offer in term.items():
            if not isinstance(offer, dict):
                continue
            dimensions = offer.get("priceDimensions", {})
            if not isinstance(dimensions, dict):
                continue
            for rate_code, dimension in dimensions.items():
                record = _record_from_aws_s3_dimension(
                    sku=sku,
                    offer_term_code=offer_term_code,
                    rate_code=rate_code,
                    dimension=dimension,
                    snapshot=snapshot,
                    document=document,
                )
                if record is not None:
                    records.append(record)
    records.sort(key=lambda item: (item.minimum_quantity or Decimal("0"), item.provider_price_code))
    return records[:1]


def _is_aws_s3_standard_storage_product(
    product: dict[str, Any], attributes: dict[str, Any]
) -> bool:
    return (
        product.get("productFamily") == "Storage"
        and attributes.get("location") == "US East (N. Virginia)"
        and attributes.get("storageClass") in {"General Purpose", "Standard"}
        and attributes.get("volumeType") == "Standard"
        and attributes.get("usagetype") == "TimedStorage-ByteHrs"
    )


def _record_from_aws_s3_dimension(
    *,
    sku: str,
    offer_term_code: str,
    rate_code: str,
    dimension: Any,
    snapshot: SnapshotRecord,
    document: SourceDocument,
) -> ExtractedPriceRecord | None:
    if not isinstance(dimension, dict):
        return None
    unit = str(dimension.get("unit") or "")
    if unit.lower() not in {"gb-mo", "gb-month"}:
        return None
    price_per_unit = dimension.get("pricePerUnit", {})
    if not isinstance(price_per_unit, dict) or "USD" not in price_per_unit:
        return None
    description = str(dimension.get("description") or "")
    begin_range = str(dimension.get("beginRange") or "0")
    end_range = str(dimension.get("endRange") or "")
    if begin_range not in {"0", "0.0"}:
        return None
    if "storage" not in description.lower():
        return None
    locator = (
        f"json:products.{sku};terms.OnDemand.{sku}.{offer_term_code}.priceDimensions.{rate_code}"
    )
    excerpt = (
        f"{description}; unit={unit}; beginRange={begin_range}; "
        f"endRange={end_range or 'Inf'}; USD={price_per_unit['USD']}"
    )
    maximum = None if end_range in {"", "Inf", "inf"} else Decimal(end_range)
    return ExtractedPriceRecord(
        provider_code="aws",
        product_code="s3",
        region_code="us-east-1",
        provider_price_code="aws_s3_us_east_1_standard_storage_first_tier_gb_month",
        charge_category=ChargeCategory.STORAGE.value,
        billing_mode=BillingMode.ON_DEMAND.value,
        billing_unit="GB-month",
        currency="USD",
        tax_included=False,
        unit_price=Decimal(str(price_per_unit["USD"])),
        minimum_quantity=Decimal(begin_range),
        maximum_quantity=maximum,
        billing_period="monthly",
        discount_type=DiscountType.LIST.value,
        evidence_type=EvidenceType.JSON_PATH.value,
        evidence_locator=locator,
        evidence_excerpt=excerpt,
        parser_rule="aws_s3_standard_storage_first_tier_v1",
        source_payload_path=str(_snapshot_payload_path(snapshot)),
        snapshot_record_id=snapshot.id,
        source_document_id=document.id,
    )
