"""Controlled import of explicitly labeled official API Explorer response copies."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.result import HttpFetchResult
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing.huawei_api import ENDPOINT, PricingQuery, validate_response

MEASURE_ENDPOINT = "https://bss.myhuaweicloud.com/v2/bases/measurements"
ECS_QUOTE_HOURS = {
    "huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2": 1,
    "huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2_730h": 730,
}
COMPONENT_SOURCE = "huawei_cloud_ecs_pricing_api_cn_north_4_components_730h"
COMPONENT_SCOPE = {
    "compute": (
        "hws.service.type.ec2",
        "hws.resource.type.vm",
        "c6.xlarge.4.linux",
        "Duration",
        730,
        4,
        None,
        None,
    ),
    "disk": (
        "hws.service.type.ebs",
        "hws.resource.type.volume",
        "GPSSD",
        "Duration",
        730,
        4,
        100,
        17,
    ),
    "traffic": (
        "hws.service.type.vpc",
        "hws.resource.type.bandwidth",
        "12_bgp",
        "upflow",
        100,
        10,
        5,
        15,
    ),
    "ip": ("hws.service.type.vpc", "hws.resource.type.ip", "5_bgp", "Duration", 730, 4, None, None),
}


def _validate_quote_scope(entry: SourceRegistryEntry, query: PricingQuery) -> None:
    if query.inquiry_precision != 1:
        raise ValueError("quote precision does not match the registered source scope")
    if entry.source_id == COMPONENT_SOURCE:
        if entry.product_code != "ecs" or {p.id for p in query.product_infos} != set(
            COMPONENT_SCOPE
        ):
            raise ValueError("component query does not match registered IDs")
        for item in query.product_infos:
            values = (
                item.cloud_service_type,
                item.resource_type,
                item.resource_spec,
                item.usage_factor,
                item.usage_value,
                item.usage_measure_id,
                item.resource_size,
                item.size_measure_id,
            )
            if (
                values != COMPONENT_SCOPE[item.id]
                or item.region != "cn-north-4"
                or item.subscription_num != 1
                or item.available_zone is not None
            ):
                raise ValueError("component query does not match registered scope")
        return
    if entry.product_code == "ecs":
        if len(query.product_infos) != 1:
            raise ValueError("only one scoped ECS quote is supported")
        service, resource, spec = "hws.service.type.ec2", "hws.resource.type.vm", "c6.large.2.linux"
        if entry.source_id not in ECS_QUOTE_HOURS:
            raise ValueError("unregistered ECS quote scope")
        factors = {"Duration": (ECS_QUOTE_HOURS[entry.source_id], 4)}
    elif entry.product_code == "obs":
        if entry.source_id != "huawei_cloud_obs_pricing_api_cn_north_4":
            raise ValueError("unregistered OBS quote scope")
        service, resource, spec = "hws.service.type.obs", "hws.resource.type.obs", "obs"
        factors = {
            "size": (1024, 10),
            "get": (1, 54),
            "put": (1, 54),
            "download.external": (100, 10),
        }
    else:
        raise ValueError("unsupported product scope")
    if len(query.product_infos) != len(factors) or {
        item.usage_factor for item in query.product_infos
    } != set(factors):
        raise ValueError("quote factors do not match the registered source scope")
    for item in query.product_infos:
        if (
            item.cloud_service_type != service
            or item.resource_type != resource
            or item.resource_spec != spec
            or item.region != "cn-north-4"
            or (item.usage_value, item.usage_measure_id) != factors[item.usage_factor]
            or item.subscription_num != 1
            or item.available_zone is not None
            or item.resource_size is not None
            or item.size_measure_id is not None
        ):
            raise ValueError("quote does not match the registered source scope")


def import_api_capture(
    session: Session,
    entry: SourceRegistryEntry,
    response_path: Path,
    captured_at: datetime,
    *,
    query: PricingQuery | None = None,
    store: SnapshotStore | None = None,
) -> dict[str, Any]:
    if (
        entry.provider_code != "huawei_cloud"
        or entry.cloud_partition != "huawei_cn"
        or entry.terms_review_status != "approved"
        or not entry.requires_authentication
        or entry.allow_automated_fetch
        or not entry.manual_only
    ):
        raise ValueError("source is not approved for controlled Huawei API import")
    if captured_at.tzinfo is None or captured_at > datetime.now(UTC):
        raise ValueError("capture timestamp must be timezone-aware and not in the future")
    raw = response_path.read_bytes()
    if not raw or len(raw) > 2_097_152:
        raise ValueError("invalid response size")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("response must be an object")
    excerpts: list[tuple[str, str]] = []
    if entry.url == ENDPOINT and query is not None:
        _validate_quote_scope(entry, query)
        validate_response(raw, query)
        if payload.get("currency") != "CNY":
            raise ValueError("quote currency must be explicit")
        requested = {item.id: item for item in query.product_infos}
        for index, row in enumerate(payload["product_rating_results"]):
            item = requested[row["id"]]
            excerpt_data = {
                "request": item.model_dump(exclude_none=True),
                "official_website_amount": row["official_website_amount"],
                "measure_id": row["measure_id"],
                "currency": payload["currency"],
                "tax_status": "unverified",
                "quantity_scope": "quoted_quantity_only",
            }
            if entry.product_code == "obs":
                excerpt_data["billing_period_status"] = (
                    "unverified" if item.usage_factor == "size" else "usage_based"
                )
            excerpts.append(
                (
                    f"json:$.product_rating_results[{index}].official_website_amount",
                    json.dumps(excerpt_data, ensure_ascii=False, sort_keys=True),
                )
            )
    elif entry.url == MEASURE_ENDPOINT and query is None:
        units = payload.get("measure_units")
        if not isinstance(units, list):
            raise ValueError("missing measurement dictionary")
        expected_units = {4: ("h", 2), 10: ("G", 3), 54: ("TTM", 4)}
        seen: set[int] = set()
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                raise ValueError("invalid measurement row")
            unit_id = unit.get("measure_id")
            if unit_id in expected_units:
                if (
                    unit_id in seen
                    or (unit.get("abbreviation"), unit.get("measure_type"))
                    != expected_units[unit_id]
                ):
                    raise ValueError("measurement definition does not match or is duplicated")
                seen.add(unit_id)
                excerpts.append(
                    (f"json:$.measure_units[{index}]", json.dumps(unit, ensure_ascii=False))
                )
        if 4 not in seen:
            raise ValueError("hour unit definition is missing")
    else:
        raise ValueError("unsupported source endpoint/query combination")
    store = store or SnapshotStore()
    metadata: dict[str, object] = {
        "capture_method": "official_api_explorer_response_clipboard_copy",
        "wire_response_bytes_available": False,
        "request_headers_stored": False,
        "external_transfer_allowed": False,
        "request": query.model_dump(exclude_none=True) if query else {},
        "http_status_observed": 200,
    }
    existing = store.find_manifest_by_hash(entry, hashlib.sha256(raw).hexdigest())
    if existing and existing[0].content_metadata.get("request") != metadata["request"]:
        raise ValueError("identical response is already associated with a different query")
    stored = store.store(
        entry=entry,
        requested_url=entry.url,
        final_url=entry.url,
        http_status=200,
        content_type="application/json",
        content=raw,
        response_headers={},
        content_metadata=metadata,
        fetch_duration_ms=0,
        captured_at=captured_at,
    )
    result = HttpFetchResult(
        entry.url,
        entry.url,
        200,
        {},
        raw,
        "application/json",
        "utf-8",
        captured_at,
        captured_at,
        0,
        0,
    )
    snapshot_id = SourceFetcher(snapshot_store=store)._record_success(
        session, entry, result, stored
    )
    snapshot = session.get(SnapshotRecord, snapshot_id)
    assert snapshot is not None
    evidence_ids = []
    for locator, excerpt in excerpts:
        evidence = session.scalar(
            select(Evidence).where(
                Evidence.snapshot_record_id == snapshot.id,
                Evidence.locator == locator,
                Evidence.parser_rule == "huawei_api_ui_copy_v1",
            )
        )
        if evidence is None:
            evidence = Evidence(
                source_document_id=snapshot.source_document_id,
                snapshot_record_id=snapshot.id,
                locator=locator,
                excerpt=excerpt,
                content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                evidence_type="json_path",
                parser_rule="huawei_api_ui_copy_v1",
                confidence=1.0,
                review_status="machine_extracted",
            )
            session.add(evidence)
            session.flush()
        evidence_ids.append(evidence.id)
    session.commit()
    return {
        "source_document_id": snapshot.source_document_id,
        "snapshot_record_id": snapshot.id,
        "evidence_ids": evidence_ids,
        "content_hash": snapshot.content_hash,
        "snapshot_created": stored.created,
        "capture_method": metadata["capture_method"],
        "price_skus_created": 0,
        "price_snapshots_created": 0,
        "remaining_checks": ["tax_scope", "tier_scope", "controlled_price_promotion"]
        + (["storage_billing_period"] if entry.product_code == "obs" else []),
    }
