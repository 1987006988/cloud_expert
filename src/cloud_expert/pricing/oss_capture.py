"""Plan or explicitly apply immutable OSS visible-excerpt evidence imports.

Default planning never persists. Explicit coordinator apply writes only snapshot
and Evidence records, never prices.
Exact visible Chinese labels are intentionally retained as source evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.result import HttpFetchResult
from cloud_expert.ingestion.storage.atomic_write import atomic_write_bytes
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore, StoredSnapshot
from cloud_expert.pricing.huawei_promotion import _get_or_create_evidence
from cloud_expert.pricing.official_catalog import decode_catalog_json

SOURCE_ID = "aliyun_oss_pricing"
RULE = "aliyun_oss_visible_excerpt_evidence_v2"
REGISTRY_URL = "https://www.aliyun.com/price/product#/oss/detail"
PAGE_URLS = {REGISTRY_URL, REGISTRY_URL + "/ossbag"}
FRAME_URL = "https://www.aliyun.com/price/detail/oss"
MAX_BYTES = 262_144
HEADING = "【公共云】中国内地地域及无地域属性（中国内地）-- 价格详情"
DISCOUNT_HEADING = "【公共云】中国内地地域官网折扣价-- 价格详情"
HEADERS = [
    "资费项",
    "计费项",
    "标准型单价",
    "低频访问型单价",
    "归档型单价",
    "冷归档型单价",
    "深度冷归档型单价",
]
ROW_CATEGORIES = {
    "数据存储（本地冗余存储）": "存储费用",
    "数据存储（同城冗余存储）": "存储费用",
    "内/外网流入流量（数据上传到 OSS）": "流量费用",
    "内网流出流量（通过同地域 ECS 使用内网 Endpoint，下载 OSS 的数据）": "流量费用",
    "外网流出流量": "流量费用",
    "PUT 类型请求": "请求费用",
    "GET 类型请求": "请求费用",
    "数据取回": "请求费用",
}
_SENSITIVE = re.compile(
    r"authorization\s*[:=]|(?:set-)?cookie\s*[:=]|bearer\s+\S+|"
    r"access[_ -]?key|secret[_ -]?key|password|session[_ -]?id|"
    r"(?:token|secret|signature|密码|密钥|账号|账户ID)\s*[:=：]|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bLTAI[A-Za-z0-9]{12,}\b|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|"
    r"<\s*/?\s*(?:script|html|iframe|form|input)\b",
    re.IGNORECASE,
)
_FORBIDDEN_SCOPE = re.compile(r"金融|国际|境外|中国香港|中国澳门|中国台湾|新加坡|美国")
Cell = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=16_384)]


class OSSVisibleCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    capture_kind: Literal["selected_visible_dom_excerpt"]
    page_url: str
    frame_url: Literal["https://www.aliyun.com/price/detail/oss"]
    captured_at: str
    section_locator: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    section_heading: Literal["【公共云】中国内地地域及无地域属性（中国内地）-- 价格详情"]
    scope_text: Text
    rows: list[list[Cell]] = Field(min_length=2, max_length=9)
    unit_text: Text
    discount_section: list[Text] = Field(max_length=1)


def _validate_registry(entry: SourceRegistryEntry) -> None:
    if (
        entry.source_id != SOURCE_ID
        or entry.url != REGISTRY_URL
        or entry.provider_code != "aliyun"
        or entry.product_code != "oss"
        or entry.market_mode != "domestic"
        or entry.cloud_partition != "aliyun_public_cn"
        or entry.authority_level != "official_primary"
        or entry.source_type != "pricing"
        or entry.terms_review_status != "approved"
        or entry.reviewed_at is None
        or entry.requires_authentication
        or not entry.requires_browser
        or not entry.manual_only
        or entry.enabled
        or entry.allow_automated_fetch
        or entry.automated_fetch_allowed is not False
        or entry.robots_allowed is False
    ):
        raise ValueError("OSS registry must authorize only this public browser/manual route")


def _scope(text: str) -> None:
    if (
        _FORBIDDEN_SCOPE.search(text)
        or "中国内地地域包括" not in text
        or "华北 2（北京）" not in text
    ):
        raise ValueError("public mainland group and explicit Beijing membership required")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_oss_capture(path: Path) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("empty or oversized OSS capture")
    return raw


def plan_oss_capture(
    raw: bytes,
    *,
    entry: SourceRegistryEntry,
    expected_sha256: str,
    as_of: datetime,
) -> dict[str, Any]:
    """Validate a pinned capture and return deterministic parent-apply candidates.

    The parent must revalidate raw bytes and registry at apply, retain original
    bytes, and reconcile immutable hashes/locators transactionally. No assumption
    about existing database rows is made by this pure planner.
    """
    _validate_registry(entry)
    if not raw or len(raw) > min(MAX_BYTES, entry.fetch_policy.max_content_length_bytes):
        raise ValueError("empty or oversized OSS capture")
    digest = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or digest != expected_sha256:
        raise ValueError("OSS capture SHA256 mismatch")
    bundle = OSSVisibleCapture.model_validate(decode_catalog_json(raw, limit=MAX_BYTES))
    if _SENSITIVE.search(_canonical(bundle.model_dump())):
        raise ValueError("sensitive content or full-page markup is not permitted")
    if bundle.page_url not in PAGE_URLS or bundle.section_locator != (
        f"div.des-title.line-title.des-mb20:has-text({HEADING})"
    ):
        raise ValueError("unapproved page route or unbound visible section locator")
    captured = datetime.fromisoformat(bundle.captured_at)
    if as_of.tzinfo is None or captured.tzinfo is None or captured > as_of:
        raise ValueError("capture and as_of must be aware; future capture forbidden")
    _scope(bundle.scope_text)
    if "按量付费方式下，各地域统一价格。" not in bundle.scope_text:
        raise ValueError("group pay-as-you-go scope is not proven")
    unit_compact = re.sub(r"\s+", "", bundle.unit_text)
    if (
        "阿里云OSS的存储容量和流量是以二进制(GB)计算" not in unit_compact
        or "1GB等于2^30字节" not in unit_compact
        or "Gibibyte(GiB)" not in unit_compact
        or "1TB等于2^40字节，即1024GB" not in unit_compact
        or re.search(r"10\^9|10\*\*9|1000000000|十进制", unit_compact)
    ):
        raise ValueError("explicit Chinese binary GB proof missing or contradictory")
    if bundle.rows[0] != HEADERS:
        raise ValueError("OSS headers missing, reordered or changed")
    current_category = None
    seen: set[str] = set()
    for row in bundle.rows[1:]:
        if len(row) != len(HEADERS) or any(not cell.strip() for cell in row):
            raise ValueError("row/header cardinality or empty cell mismatch")
        expected_category = ROW_CATEGORIES.get(row[1])
        if expected_category is None or row[1] in seen:
            raise ValueError("unrecognized or duplicate OSS billing row")
        seen.add(row[1])
        if row[0] != "-":
            current_category = row[0]
        if current_category != expected_category:
            raise ValueError("row category inheritance is not proven")
    for discount in bundle.discount_section:
        if not discount.startswith(DISCOUNT_HEADING) or "目录价基础上叠加一定折扣" not in discount:
            raise ValueError("public discount section must be explicitly separated and labeled")
        _scope(discount)

    scope = {
        "market_mode": "domestic",
        "cloud_partition": "aliyun_public_cn",
        "target_region": "cn-beijing",
        "region_selected_in_ui": False,
        "region_basis": "explicit_membership_in_visible_mainland_public_cloud_group",
        "billing_mode": "pay_as_you_go",
        "other_regions_normalized": False,
        "financial_or_international_scope_inferred": False,
    }
    snapshot_key = hashlib.sha256(f"{SOURCE_ID}:{digest}".encode()).hexdigest()
    evidence: list[dict[str, Any]] = []

    def add(locator: str, value: Any, basis: str) -> None:
        excerpt = _canonical(value)
        excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        evidence.append(
            {
                "idempotency_key": hashlib.sha256(
                    f"{snapshot_key}:{RULE}:{locator}".encode()
                ).hexdigest(),
                "locator": locator,
                "excerpt": excerpt,
                "content_hash": excerpt_hash,
                "parser_rule": RULE,
                "evidence_type": "json_path",
                "review_status": "machine_extracted",
                "confidence": 1.0,
                "confidence_meaning": "exact_capture_transcription_not_price_approval",
                "price_basis": basis,
                "scope": scope,
            }
        )

    add("json:/section_heading", bundle.section_heading, "list_section_context")
    add("json:/scope_text", bundle.scope_text, "list_section_scope")
    add("json:/unit_text", bundle.unit_text, "binary_unit_policy_excerpt")
    add("json:/rows/0", bundle.rows[0], "list_column_headers")
    for index, row in enumerate(bundle.rows[1:], start=1):
        add(f"json:/rows/{index}", row, "public_list_visible_row")
    for index, discount in enumerate(bundle.discount_section):
        add(f"json:/discount_section/{index}", discount, "public_discount_separate_unapproved")
    plan = {
        "schema_version": "1.0",
        "rule_version": RULE,
        "mode": "dry_run",
        "status": "snapshot_evidence_plan_only",
        "source_id": SOURCE_ID,
        "registry_sha256": hashlib.sha256(
            _canonical(entry.model_dump(mode="json", exclude={"registry_file"})).encode()
        ).hexdigest(),
        "snapshot_idempotency_key": snapshot_key,
        "source_document_identity": {"url": entry.url, "content_hash": digest},
        "snapshot_candidate": {
            "source_id": SOURCE_ID,
            "requested_url": entry.url,
            "observed_page_url": bundle.page_url,
            "observed_frame_url": bundle.frame_url,
            "captured_at": bundle.captured_at,
            "content_sha256": digest,
            "content_length_bytes": len(raw),
            "content_type": "application/json",
            "capture_kind": bundle.capture_kind,
            "section_locator": bundle.section_locator,
            "http_status": None,
            "http_status_observed": False,
            "full_html_available": False,
            "full_dom_available": False,
            "wire_response_bytes_available": False,
            "retain_input_bytes_without_reserialization": True,
        },
        "evidence_candidates": evidence,
        "scope": scope,
        "unit_evidence": {
            "display_unit": "GB",
            "bytes_per_unit": 2**30,
            "applies_to": ["storage_capacity", "traffic"],
            "locator": "json:/unit_text",
        },
        "unresolved_semantics": {
            "tax_status": "unknown",
            "tariff_timezone": "unknown",
            "month_basis": "unknown",
            "proration": "unknown",
            "free_grant_eligibility_and_aggregation": "unknown",
            "public_discount_eligibility": "unknown",
            "currency_iso_code": "unverified",
            "storage_minimum_duration": "unknown",
        },
        "price_skus_created": 0,
        "price_snapshots_created": 0,
        "database_write_performed": False,
        "snapshot_write_performed": False,
        "customer_output_eligible": False,
        "promotion_allowed": False,
        "parent_apply_requirements": [
            "Revalidate exact raw hash, size and current registry approval at apply time.",
            "Persist original bytes and original captured_at; never label excerpt as full HTML or wire response.",
            "Reuse snapshot by source_id/content hash and SourceDocument by URL/content hash.",
            "Reconcile Evidence by snapshot/parser_rule/locator; equal excerpt/hash is a no-op; mismatch must abort.",
            "Use one controlled transaction, preserve history, and never replace a newer current snapshot with this older capture.",
            "Do not create PriceSKU or PriceSnapshot until tax/time/free-grant and discount semantics are separately evidenced.",
        ],
    }
    plan["plan_sha256"] = hashlib.sha256(_canonical(plan).encode()).hexdigest()
    return plan


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _verify_stored(store: SnapshotStore, manifest_path: Path, plan: dict[str, Any]) -> None:
    root = store.raw_data_dir.resolve()
    if not manifest_path.resolve().is_relative_to(root):
        raise ValueError("stored manifest escapes snapshot root")
    manifest = store.load_manifest(manifest_path)
    candidate = plan["snapshot_candidate"]
    raw_path = (root / manifest.storage_path).resolve()
    if not raw_path.is_relative_to(root):
        raise ValueError("stored raw escapes snapshot root")
    retained = read_oss_capture(raw_path)
    if (
        manifest.source_id != SOURCE_ID
        or manifest.provider_code != "aliyun"
        or str(manifest.market_mode) != "domestic"
        or manifest.product_code != "oss"
        or str(manifest.source_type) != "pricing"
        or manifest.requested_url != REGISTRY_URL
        or manifest.final_url != REGISTRY_URL
        or manifest.http_status != 0
        or manifest.content_type != "application/json"
        or manifest.content_sha256 != candidate["content_sha256"]
        or manifest.content_length_bytes != candidate["content_length_bytes"]
        or _utc(manifest.captured_at) != datetime.fromisoformat(candidate["captured_at"])
        or hashlib.sha256(retained).hexdigest() != candidate["content_sha256"]
        or len(retained) != candidate["content_length_bytes"]
        or any(
            manifest.content_metadata.get(key) != candidate[key]
            for key in (
                "capture_kind",
                "observed_page_url",
                "observed_frame_url",
                "section_locator",
                "full_html_available",
                "full_dom_available",
                "wire_response_bytes_available",
                "http_status_observed",
            )
        )
        or manifest.content_metadata.get("original_captured_at") != candidate["captured_at"]
    ):
        raise ValueError("existing immutable OSS snapshot provenance/integrity mismatch")


def _check_document(snapshot: SnapshotRecord, plan: dict[str, Any]) -> None:
    candidate = plan["snapshot_candidate"]
    doc = snapshot.source_document
    if (
        snapshot.content_hash != candidate["content_sha256"]
        or snapshot.content_length_bytes != candidate["content_length_bytes"]
        or snapshot.content_type != "application/json"
        or _utc(snapshot.captured_at) != datetime.fromisoformat(candidate["captured_at"])
        or doc.content_hash != snapshot.content_hash
        or doc.storage_path != snapshot.storage_path
        or doc.url != REGISTRY_URL
        or doc.cloud_partition != "aliyun_public_cn"
        or doc.source_type != "pricing"
        or doc.authority_level != "official_primary"
        or doc.mime_type != "application/json"
        or doc.http_status is not None
        or doc.provider.code != "aliyun"
        or _utc(doc.captured_at) != _utc(snapshot.captured_at)
    ):
        raise ValueError("existing OSS database provenance differs")


def apply_oss_capture(
    session: Session,
    path: Path,
    *,
    expected_sha256: str,
    previous_plan_sha256: str,
    as_of: datetime,
    store: SnapshotStore | None = None,
) -> dict[str, Any]:
    """Coordinator-only commit; revalidate raw/current registry against a dry-run hash.

    Requires a fresh session and supports PostgreSQL plus isolated SQLite tests.
    DB changes are atomic, including the legacy fetcher's internal commit. Raw
    immutable files survive failed attempts for audit/retry; latest.json is
    restored on handled failure. A process crash can leave an orphan snapshot
    pointer and must be reconciled from the DB, never treated as DB approval.
    """
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise ValueError("OSS apply requires a fresh dedicated session")
    if not re.fullmatch(r"[a-f0-9]{64}", previous_plan_sha256):
        raise ValueError("previous dry-run plan SHA256 required")
    store = store or SnapshotStore()
    stored: StoredSnapshot | None = None
    pointer: Path | None = None
    pointer_before: bytes | None = None
    pointer_touched = False
    result: dict[str, Any]
    try:
        with session.begin():
            connection = session.connection()
            if connection.dialect.name == "postgresql":
                lock_id = int.from_bytes(
                    hashlib.sha256(SOURCE_ID.encode()).digest()[:8], "big", signed=True
                )
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
            elif connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                raise ValueError("unsupported transaction dialect for OSS apply")
            entry = get_entry_by_source_id(SOURCE_ID)
            if entry is None:
                raise ValueError("OSS registry is missing")
            raw = read_oss_capture(path)
            plan = plan_oss_capture(raw, entry=entry, expected_sha256=expected_sha256, as_of=as_of)
            if plan["plan_sha256"] != previous_plan_sha256:
                raise ValueError("current raw/registry/plan differs from approved dry run")
            candidate = plan["snapshot_candidate"]
            captured = datetime.fromisoformat(candidate["captured_at"])
            snapshot = session.scalar(
                select(SnapshotRecord).where(
                    SnapshotRecord.source_id == SOURCE_ID,
                    SnapshotRecord.content_hash == expected_sha256,
                )
            )
            snapshot_created = snapshot is None
            if snapshot is None:
                current = session.scalar(
                    select(SnapshotRecord)
                    .where(
                        SnapshotRecord.source_id == SOURCE_ID, SnapshotRecord.is_current.is_(True)
                    )
                    .order_by(SnapshotRecord.captured_at.desc())
                )
                if current is not None and _utc(current.captured_at) >= captured:
                    raise ValueError(
                        "older or same-time different capture cannot replace current snapshot"
                    )
                if (
                    session.scalar(
                        select(SourceDocument.id).where(
                            SourceDocument.url == REGISTRY_URL,
                            SourceDocument.content_hash == expected_sha256,
                        )
                    )
                    is not None
                ):
                    raise ValueError("unlinked existing SourceDocument requires reconciliation")
                duplicate = store.find_manifest_by_hash(entry, expected_sha256)
                if duplicate:
                    _verify_stored(store, duplicate[1], plan)
                latest = store.latest_manifest(entry)
                if latest and _utc(latest[0].captured_at) > captured:
                    raise ValueError("newer retained capture requires reconciliation before apply")
                pointer = store.latest_pointer_path(entry)
                if pointer.exists():
                    with pointer.open("rb") as handle:
                        pointer_before = handle.read(65_537)
                    if len(pointer_before) > 65_536:
                        raise ValueError("oversized latest pointer")
                pointer_touched = True
                stored = store.store(
                    entry=entry,
                    requested_url=entry.url,
                    final_url=entry.url,
                    http_status=0,
                    content_type="application/json",
                    content=raw,
                    response_headers={},
                    content_metadata={
                        **candidate,
                        "original_captured_at": candidate["captured_at"],
                        "http_status_sentinel": "0 means not observed, not HTTP success",
                        "plan_sha256_at_first_import": previous_plan_sha256,
                        "rule_version": RULE,
                        "price_promotion_permitted": False,
                        "registry_sha256_at_first_import": plan["registry_sha256"],
                    },
                    fetch_duration_ms=0,
                    captured_at=captured,
                )
                _verify_stored(store, stored.manifest_path, plan)
                fetched = HttpFetchResult(
                    entry.url,
                    entry.url,
                    0,
                    {},
                    raw,
                    "application/json",
                    "utf-8",
                    captured,
                    captured,
                    0,
                    0,
                )
                # The legacy helper commits. A savepoint-bound child keeps that
                # commit inside our still-open outer transaction until all E exists.
                with Session(bind=connection, join_transaction_mode="create_savepoint") as child:
                    snapshot_id = SourceFetcher(snapshot_store=store)._record_success(
                        child, entry, fetched, stored
                    )
                snapshot = session.get(SnapshotRecord, snapshot_id)
                if snapshot is None:
                    raise ValueError("snapshot creation did not return a record")
                snapshot.source_document.http_status = None
                session.flush()
            else:
                _verify_stored(store, store.raw_data_dir / snapshot.manifest_path, plan)
                manifest = store.load_manifest(store.raw_data_dir / snapshot.manifest_path)
                if snapshot.storage_path != manifest.storage_path:
                    raise ValueError("DB snapshot path differs from immutable manifest")
            _check_document(snapshot, plan)
            evidence_ids: list[int] = []
            created_ids: list[int] = []
            existing_ids: list[int] = []
            for item in plan["evidence_candidates"]:
                previous = list(
                    session.scalars(
                        select(Evidence).where(
                            Evidence.snapshot_record_id == snapshot.id,
                            Evidence.locator == item["locator"],
                            Evidence.parser_rule == RULE,
                        )
                    )
                )
                if len(previous) > 1 or (
                    previous
                    and (
                        previous[0].source_document_id != snapshot.source_document_id
                        or previous[0].evidence_type != item["evidence_type"]
                    )
                ):
                    raise ValueError("conflicting existing OSS evidence lineage")
                row = _get_or_create_evidence(
                    session, snapshot, item["locator"], item["excerpt"], RULE
                )
                if not previous:
                    row.evidence_type = item["evidence_type"]
                    created_ids.append(row.id)
                else:
                    existing_ids.append(row.id)
                evidence_ids.append(row.id)
            session.flush()
            if snapshot_created and stored is not None and pointer is not None:
                atomic_write_bytes(
                    pointer,
                    _canonical(
                        {
                            "snapshot_id": stored.manifest.snapshot_id,
                            "manifest_path": str(
                                stored.manifest_path.relative_to(store.raw_data_dir)
                            ),
                            "content_sha256": expected_sha256,
                            "captured_at": stored.manifest.captured_at.isoformat(),
                        }
                    ).encode(),
                )
            result = {
                "mode": "apply",
                "status": "snapshot_evidence_committed",
                "source_document_id": snapshot.source_document_id,
                "snapshot_record_id": snapshot.id,
                "snapshot_created": snapshot_created,
                "snapshot_is_current": snapshot.is_current,
                "evidence_ids": evidence_ids,
                "evidence_created_ids": created_ids,
                "evidence_existing_ids": existing_ids,
                "raw_sha256": expected_sha256,
                "plan_sha256": previous_plan_sha256,
                "captured_at": candidate["captured_at"],
                "price_skus_created": 0,
                "price_snapshots_created": 0,
                "customer_output_eligible": False,
                "promotion_allowed": False,
                "database_write_performed": snapshot_created or bool(created_ids),
                "unresolved_semantics": plan["unresolved_semantics"],
            }
        return result
    except Exception:
        if pointer_touched and pointer is not None:
            if pointer_before is None:
                pointer.unlink(missing_ok=True)
            else:
                atomic_write_bytes(pointer, pointer_before)
        raise
