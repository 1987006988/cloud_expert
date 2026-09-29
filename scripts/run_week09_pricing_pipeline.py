from __future__ import annotations

import csv
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import SourceType
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.tco import CostCalculationRun, CostLineItem, TCOResult
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.pricing.extraction import extract_price_records, persist_price_records
from cloud_expert.pricing.source_policy import approved_collection, collection_mode
from cloud_expert.pricing.tco import RUN_CODE, generate_internal_tco

REPORT_DIR = _ROOT / "reports" / "week09_pricing"

REQUIRED_PRICING_SOURCES = {
    ("huawei_cloud", "ecs"),
    ("huawei_cloud", "obs"),
    ("aws", "ec2"),
    ("aws", "s3"),
    ("aliyun", "ecs"),
    ("aliyun", "oss"),
}


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _pricing_entries() -> list[SourceRegistryEntry]:
    return [
        entry for entry in load_registry_entries() if entry.source_type == SourceType.PRICING.value
    ]


def _collection_mode(entry: SourceRegistryEntry) -> str:
    return collection_mode(entry)


def audit_pricing_sources(entries: list[SourceRegistryEntry]) -> dict[str, Any]:
    registered = {(entry.provider_code, entry.product_code or "") for entry in entries}
    approved = {
        (entry.provider_code, entry.product_code or "")
        for entry in entries
        if approved_collection(entry)
    }
    missing_approved = sorted(
        f"{provider}/{product}"
        for provider, product in REQUIRED_PRICING_SOURCES
        if (provider, product) not in approved
    )
    missing = sorted(
        f"{provider}/{product}"
        for provider, product in REQUIRED_PRICING_SOURCES
        if (provider, product) not in registered
    )
    source_rows = []
    errors: list[str] = []
    for entry in entries:
        mode = _collection_mode(entry)
        if entry.terms_review_status != "approved" and mode != "retired_no_collection":
            errors.append(f"{entry.source_id}: terms_review_status is not approved")
        if mode == "blocked_or_misconfigured":
            errors.append(f"{entry.source_id}: collection mode is not approved")
        source_rows.append(
            {
                "source_id": entry.source_id,
                "provider": entry.provider_code,
                "product": entry.product_code,
                "url": entry.url,
                "enabled": entry.enabled,
                "allow_automated_fetch": entry.allow_automated_fetch,
                "manual_only": entry.manual_only,
                "terms_review_status": entry.terms_review_status,
                "collection_mode": mode,
                "user_agent_profile": entry.fetch_policy.user_agent_profile,
            }
        )
    if missing:
        errors.append("missing required provider/product pricing registry entries")
    if missing_approved:
        errors.append("missing approved collection route for required provider/product")
    return {
        "generated_at": _now(),
        "required_provider_products": sorted(
            f"{provider}/{product}" for provider, product in REQUIRED_PRICING_SOURCES
        ),
        "registered_pricing_sources": len(entries),
        "missing_required": missing,
        "missing_approved_collection_routes": missing_approved,
        "automated_sources": [
            row["source_id"]
            for row in source_rows
            if row["collection_mode"] == "automated_http_snapshot"
        ],
        "manual_sources": [
            row["source_id"]
            for row in source_rows
            if row["collection_mode"] == "manual_or_browser_snapshot_required"
        ],
        "sources": source_rows,
        "errors": errors,
        "valid": not errors,
    }


def fetch_automated_sources(
    entries: list[SourceRegistryEntry], *, force: bool
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    fetcher = SourceFetcher()
    fetchable = [
        entry
        for entry in entries
        if entry.enabled and entry.allow_automated_fetch and not entry.manual_only
    ]
    with SessionLocal() as session:
        for entry in fetchable:
            outcome = fetcher.fetch(entry, session=session, force=force)
            outcomes.append(
                {
                    "source_id": outcome.source_id,
                    "status": outcome.status,
                    "http_status": outcome.http_status,
                    "content_type": outcome.content_type,
                    "bytes_downloaded": outcome.bytes_downloaded,
                    "snapshot_record_id": outcome.snapshot_record_id,
                    "snapshot_id": outcome.snapshot_id,
                    "manifest_path": outcome.manifest_path,
                    "error_code": outcome.error_code,
                    "error_message": outcome.error_message,
                }
            )
    return outcomes


def extract_and_persist_prices() -> dict[str, Any]:
    with SessionLocal() as session:
        records = extract_price_records(session)
        result = persist_price_records(session, records)
        result["records"] = [
            {
                "provider": record.provider_code,
                "product": record.product_code,
                "region": record.region_code,
                "provider_price_code": record.provider_price_code,
                "billing_unit": record.billing_unit,
                "currency": record.currency,
                "unit_price": str(record.unit_price),
                "discount_type": record.discount_type,
                "source_document_id": record.source_document_id,
                "snapshot_record_id": record.snapshot_record_id,
                "evidence_locator": record.evidence_locator,
            }
            for record in records
        ]
        return result


def generate_tco() -> dict[str, Any]:
    with SessionLocal() as session:
        return generate_internal_tco(session)


def database_counts() -> dict[str, int]:
    with SessionLocal() as session:
        return {
            "pricing_source_documents": session.scalar(
                select(func.count())
                .select_from(SourceDocument)
                .where(SourceDocument.source_type == SourceType.PRICING.value)
            )
            or 0,
            "pricing_evidence": session.scalar(
                select(func.count())
                .select_from(Evidence)
                .join(SourceDocument, Evidence.source_document_id == SourceDocument.id)
                .where(SourceDocument.source_type == SourceType.PRICING.value)
            )
            or 0,
            "price_skus": session.scalar(select(func.count()).select_from(PriceSKU)) or 0,
            "price_snapshots": session.scalar(select(func.count()).select_from(PriceSnapshot)) or 0,
            "cost_runs": session.scalar(select(func.count()).select_from(CostCalculationRun)) or 0,
            "cost_line_items": session.scalar(select(func.count()).select_from(CostLineItem)) or 0,
            "tco_results": session.scalar(select(func.count()).select_from(TCOResult)) or 0,
        }


def snapshot_manifest() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(SnapshotRecord, SourceDocument)
            .join(SourceDocument, SnapshotRecord.source_document_id == SourceDocument.id)
            .where(SourceDocument.source_type == SourceType.PRICING.value)
            .order_by(SnapshotRecord.source_id, SnapshotRecord.captured_at.desc())
        ).all()
    return [
        {
            "source_id": snapshot.source_id,
            "source_document_id": document.id,
            "snapshot_record_id": snapshot.id,
            "title": document.title,
            "url": document.url,
            "captured_at": snapshot.captured_at.isoformat(),
            "content_hash": snapshot.content_hash,
            "storage_path": snapshot.storage_path,
            "manifest_path": snapshot.manifest_path,
            "is_current": snapshot.is_current,
        }
        for snapshot, document in rows
    ]


def tco_detail_rows() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        run = session.scalar(
            select(CostCalculationRun).where(CostCalculationRun.run_code == RUN_CODE)
        )
        if run is None:
            return []
        rows = session.execute(
            select(CostLineItem, Provider, Product)
            .join(Provider, CostLineItem.provider_id == Provider.id)
            .join(Product, CostLineItem.product_id == Product.id)
            .where(CostLineItem.run_id == run.id)
            .order_by(Provider.code, Product.code, CostLineItem.dimension)
        ).all()
    return [
        {
            "provider": provider.code,
            "product": product.code,
            "dimension": item.dimension,
            "usage_quantity": str(item.usage_quantity) if item.usage_quantity is not None else "",
            "usage_unit": item.usage_unit or "",
            "unit_price": str(item.unit_price) if item.unit_price is not None else "",
            "currency": item.currency or "",
            "amount": str(item.amount) if item.amount is not None else "",
            "price_snapshot_id": item.price_snapshot_id or "",
            "evidence_id": item.evidence_id or "",
            "missing_reason": item.missing_reason or "",
            "warning": item.warning or "",
        }
        for item, provider, product in rows
    ]


def _write_json(name: str, payload: Any) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        REPORT_DIR / name,
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
    )


def _write_source_audit(audit: dict[str, Any]) -> None:
    lines = [
        "# Week 9 Pricing Source Audit",
        "",
        f"Generated at: {audit['generated_at']}",
        "",
        f"Audit valid: **{audit['valid']}**",
        "",
        "| Source | Provider/Product | Collection mode | Terms | URL |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in audit["sources"]:
        lines.append(
            "| {source_id} | {provider}/{product} | {collection_mode} | "
            "{terms_review_status} | {url} |".format(**row)
        )
    if audit["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in audit["errors"])
    atomic_write_text(REPORT_DIR / "source_audit.md", "\n".join(lines) + "\n")


def _write_tco_detail(rows: list[dict[str, Any]]) -> None:
    csv_path = REPORT_DIR / "tco_detail.csv"
    md_path = REPORT_DIR / "tco_detail.md"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "provider",
        "product",
        "dimension",
        "usage_quantity",
        "usage_unit",
        "unit_price",
        "currency",
        "amount",
        "price_snapshot_id",
        "evidence_id",
        "missing_reason",
        "warning",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Week 9 TCO Detail",
        "",
        "| Provider | Product | Dimension | Usage | Unit price | Amount | Evidence | Status |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        status = row["missing_reason"] or row["warning"] or "priced"
        lines.append(
            "| {provider} | {product} | {dimension} | {usage_quantity} {usage_unit} | "
            "{unit_price} {currency} | {amount} {currency} | {evidence_id} | {status} |".format(
                **row, status=status
            )
        )
    atomic_write_text(md_path, "\n".join(lines) + "\n")


def write_reports(payload: dict[str, Any]) -> None:
    audit = payload["source_audit"]
    _write_json("validation_results.json", payload)
    _write_json("source_audit.json", audit)
    _write_json("snapshot_manifest.json", payload["snapshot_manifest"])
    _write_json("price_records.json", payload["price_records"])
    _write_json("tco_detail.json", payload["tco_detail"])
    _write_source_audit(audit)
    _write_tco_detail(payload["tco_detail"])


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run Week 9 official pricing pipeline.")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--force-fetch", action="store_true")
    args = parser.parse_args()

    entries = _pricing_entries()
    audit = audit_pricing_sources(entries)
    fetch_outcomes = (
        [] if args.skip_fetch else fetch_automated_sources(entries, force=args.force_fetch)
    )
    price_records = extract_and_persist_prices()
    tco = generate_tco()
    payload = {
        "generated_at": _now(),
        "source_audit": audit,
        "fetch_outcomes": fetch_outcomes,
        "price_records": price_records,
        "tco": tco,
        "database_counts": database_counts(),
        "snapshot_manifest": snapshot_manifest(),
        "tco_detail": tco_detail_rows(),
        "notes": [
            "Only price values linked to official SourceDocument and Evidence are persisted.",
            "Missing prices remain NULL with missing_reason; they are not treated as zero.",
            "This Week 9 output is internal and not customer eligible.",
        ],
    }
    write_reports(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
