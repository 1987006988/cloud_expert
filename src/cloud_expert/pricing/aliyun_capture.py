"""Import public browser catalog evidence without claiming live quote eligibility."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore

SOURCE_ID = "aliyun_ecs_pricing"
RULE = "aliyun_browser_catalog_evidence_v1"


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed > datetime.now(UTC):
        raise ValueError("invalid browser capture timestamp")
    return parsed.astimezone(UTC)


def inspect_catalog(raw: bytes) -> tuple[datetime, list[dict[str, Any]]]:
    if not raw or len(raw) > 10_485_760:
        raise ValueError("invalid browser capture size")
    bundle = json.loads(raw)
    if (
        bundle.get("schema_version") != 1
        or bundle.get("source_code") != SOURCE_ID
        or bundle.get("capture_method") != "browser_rendered_dom_bundle"
    ):
        raise ValueError("unsupported browser capture format")
    sections = bundle.get("sections", [])
    if len(sections) != 3 or {s.get("section") for s in sections} != {"compute", "disk", "network"}:
        raise ValueError("compute, disk and network sections are required")
    records: list[dict[str, Any]] = []
    times = []
    for section in sections:
        times.append(_timestamp(section["captured_at"]))
        url = urlsplit(section["url"])
        if (
            url.scheme != "https"
            or url.netloc != "www.aliyun.com"
            or url.path != "/price/product"
            or url.fragment not in {"/ecs/detail", "/ecs/detail/vm"}
        ):
            raise ValueError("unapproved catalog URL")
        region = BeautifulSoup(section["region_html"], "html.parser").find("button")
        if (
            region is None
            or region.get("value") != "cn-beijing"
            or "ant-radio-button-wrapper-checked" not in region.get_attribute_list("class")
        ):
            raise ValueError("Beijing region selection is not proven")
        context = section["page_ax"]
        if "非实时价格" not in context or "不关联个人优惠" not in context:
            raise ValueError("catalog limitations are missing")
        section_count = 0
        for table_index, html in enumerate(section["tables"]):
            table = BeautifulSoup(html, "html.parser").find("table")
            if table is None:
                raise ValueError("invalid captured table")
            headers = [cell.get_text(" ", strip=True) for cell in table.select("thead th")]
            for row_index, row in enumerate(table.select("tbody tr")):
                cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
                if not cells or not any("￥" in value or "元" in value for value in cells):
                    continue
                # Preserve labeled cells verbatim; unknown units/tax are not inferred.
                records.append(
                    {
                        "section": section["section"],
                        "table_index": table_index,
                        "row_index": row_index,
                        "headers": headers,
                        "cells": cells,
                        "region": "cn-beijing",
                        "captured_at": section["captured_at"],
                        "catalog_only": True,
                        "realtime": False,
                        "tax_status": "unverified",
                        "customer_quote_eligible": False,
                    }
                )
                section_count += 1
        if not section_count:
            raise ValueError("section contains no price rows")
    return min(times), records


def import_catalog(
    session: Session, entry: SourceRegistryEntry, path: Path, *, store: SnapshotStore | None = None
) -> dict[str, Any]:
    if (
        entry.source_id != SOURCE_ID
        or entry.url != "https://www.aliyun.com/price/product#/ecs/detail"
        or entry.provider_code != "aliyun"
        or entry.product_code != "ecs"
        or entry.cloud_partition != "aliyun_public_cn"
        or entry.terms_review_status != "approved"
        or not entry.manual_only
        or not entry.requires_browser
        or entry.allow_automated_fetch
    ):
        raise ValueError("catalog source is not approved for browser import")
    raw = path.read_bytes()
    captured, records = inspect_catalog(raw)
    digest = hashlib.sha256(raw).hexdigest()
    store = store or SnapshotStore()
    provider = session.scalar(select(Provider).where(Provider.code == entry.provider_code))
    if provider is None:
        raise ValueError("provider must already be registered")
    snapshot = session.scalar(
        select(SnapshotRecord).where(
            SnapshotRecord.source_id == entry.source_id, SnapshotRecord.content_hash == digest
        )
    )
    created = snapshot is None
    if snapshot is None:
        previous = session.scalar(
            select(SnapshotRecord).where(
                SnapshotRecord.source_id == entry.source_id, SnapshotRecord.is_current.is_(True)
            )
        )
        if previous and previous.captured_at.replace(tzinfo=UTC) > captured:
            raise ValueError("older capture cannot replace the current catalog")
        stored = store.store(
            entry=entry,
            requested_url=entry.url,
            final_url=entry.url,
            http_status=0,
            content_type="application/json",
            content=raw,
            response_headers={},
            content_metadata={
                "capture_method": "browser_rendered_dom_bundle",
                "http_status_observed": False,
                "http_status_sentinel": "0 means not observed, not HTTP success",
                "wire_response_bytes_available": False,
                "catalog_only": True,
                "realtime": False,
                "capture_time_policy": "earliest section for conservative freshness",
            },
            fetch_duration_ms=0,
            captured_at=captured,
        )
        document = SourceDocument(
            provider_id=provider.id,
            source_type="pricing",
            title=entry.title,
            url=entry.url,
            cloud_partition=entry.cloud_partition,
            language=entry.language,
            authority_level=str(entry.authority_level),
            captured_at=captured,
            content_hash=digest,
            storage_path=stored.manifest.storage_path,
            mime_type="application/json",
            http_status=None,
            is_current=True,
        )
        session.add(document)
        session.flush()
        if previous:
            previous.is_current = False
            previous.source_document.is_current = False
        snapshot = SnapshotRecord(
            source_document_id=document.id,
            source_id=entry.source_id,
            content_hash=digest,
            storage_path=stored.manifest.storage_path,
            manifest_path=str(stored.manifest_path.relative_to(store.raw_data_dir)),
            content_type="application/json",
            content_length_bytes=len(raw),
            captured_at=captured,
            previous_snapshot_id=previous.id if previous else None,
            change_status=stored.manifest.change_status,
            is_current=True,
        )
        session.add(snapshot)
        session.flush()
    else:
        stored_path = (store.raw_data_dir / snapshot.storage_path).resolve()
        if (
            not stored_path.is_relative_to(store.raw_data_dir)
            or hashlib.sha256(stored_path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("existing catalog raw snapshot integrity failure")
    ids = []
    for record in records:
        locator = (
            f"browser:{record['section']}:table[{record['table_index']}]:row[{record['row_index']}]"
        )
        excerpt = json.dumps(record, ensure_ascii=False, sort_keys=True)
        evidence = session.scalar(
            select(Evidence).where(
                Evidence.snapshot_record_id == snapshot.id,
                Evidence.locator == locator,
                Evidence.parser_rule == RULE,
            )
        )
        if evidence is None:
            evidence = Evidence(
                source_document_id=snapshot.source_document_id,
                snapshot_record_id=snapshot.id,
                locator=locator,
                excerpt=excerpt,
                content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                evidence_type="html_section",
                parser_rule=RULE,
                confidence=1.0,
                review_status="machine_extracted",
            )
            session.add(evidence)
            session.flush()
        elif (
            evidence.excerpt != excerpt
            or evidence.content_hash != hashlib.sha256(excerpt.encode()).hexdigest()
        ):
            raise ValueError("existing immutable catalog evidence differs")
        ids.append(evidence.id)
    session.commit()
    return {
        "source_document_id": snapshot.source_document_id,
        "snapshot_record_id": snapshot.id,
        "snapshot_created": created,
        "content_hash": digest,
        "evidence_ids": ids,
        "price_skus_created": 0,
        "price_snapshots_created": 0,
        "customer_output_eligible": False,
        "remaining_checks": ["tax_scope", "live_quote_or_catalog_scope_approval", "sku_scope"],
    }
