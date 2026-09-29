"""Narrow AWS billing policies re-extracted from retained official HTML, offline."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.pricing.official_catalog import decode_catalog_json

RULE = "aws_official_billing_policy_v1"
POLICY_SOURCES = {
    "s3": "aws_s3_pricing",
    "ec2": "aws_ec2_pricing_on_demand",
}
POLICY_PATHS = {"s3": "s3/pricing/", "ec2": "ec2/pricing/on-demand/"}
TAX_CLAUSE = "除非另行说明，否则我们的价格不包含适用的税费和关税（包括增值税和适用的销售税）"


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def within(root: Path, relative: str) -> Path:
    path = (root.resolve() / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("snapshot path escapes raw root")
    return path


def verified_snapshot(
    session: Session, snapshot_id: int, *, raw_root: Path, as_of: datetime, max_age_days: int
) -> tuple[SnapshotRecord, SourceRegistryEntry, dict[str, Any], Path]:
    """Bind DB/manifest/registry identities. Caller must verify raw bytes before use."""
    if as_of.tzinfo is None or type(max_age_days) is not int or not 1 <= max_age_days <= 90:
        raise ValueError("aware time and bounded freshness policy required")
    snapshot = session.get(SnapshotRecord, snapshot_id)
    if snapshot is None:
        raise ValueError("snapshot missing")
    entry = get_entry_by_source_id(snapshot.source_id)
    document = snapshot.source_document
    if (
        entry is None
        or entry.provider_code != "aws"
        or entry.market_mode != "international"
        or entry.cloud_partition != "aws"
        or entry.product_code not in POLICY_PATHS
        or entry.source_type != "pricing"
        or entry.authority_level != "official_primary"
        or entry.terms_review_status != "approved"
        or entry.reviewed_at is None
        or not entry.enabled
        or not entry.allow_automated_fetch
        or entry.automated_fetch_allowed is not True
        or entry.manual_only
        or entry.requires_authentication
        or entry.requires_browser
        or entry.robots_allowed is False
        or document.provider.code != "aws"
        or document.cloud_partition != "aws"
        or document.source_type != "pricing"
        or document.authority_level != "official_primary"
        or not document.is_current
        or not snapshot.is_current
        or document.content_hash != snapshot.content_hash
        or document.storage_path != snapshot.storage_path
        or document.mime_type != snapshot.content_type
        or document.http_status != 200
        or utc(document.captured_at) != utc(snapshot.captured_at)
        or not timedelta(0) <= as_of - utc(snapshot.captured_at) <= timedelta(days=max_age_days)
    ):
        raise ValueError("official snapshot provenance, authorization or freshness invalid")
    manifest_path = within(raw_root, snapshot.manifest_path)
    manifest = decode_catalog_json(manifest_path.read_bytes(), limit=1024 * 1024)
    if not isinstance(manifest, dict):
        raise ValueError("manifest object required")
    captured = datetime.fromisoformat(manifest.get("captured_at", ""))
    if (
        captured.tzinfo is None
        or utc(captured) != utc(snapshot.captured_at)
        or manifest.get("schema_version") != "1.0"
        or any(
            manifest.get(key) != getattr(entry, key)
            for key in ("source_id", "provider_code", "market_mode", "product_code", "source_type")
        )
        or manifest.get("requested_url") != entry.url
        or manifest.get("final_url") != document.url
        or manifest.get("http_status") != 200
        or manifest.get("storage_path") != snapshot.storage_path
        or manifest.get("content_sha256") != snapshot.content_hash
        or manifest.get("content_length_bytes") != snapshot.content_length_bytes
        or manifest.get("content_type") != snapshot.content_type
        or snapshot.content_type not in entry.expected_content_type
    ):
        raise ValueError("snapshot manifest differs from database or registry")
    raw_path = within(raw_root, snapshot.storage_path)
    if not raw_path.is_file() or raw_path.stat().st_size != snapshot.content_length_bytes:
        raise ValueError("raw snapshot byte count mismatch")
    return snapshot, entry, manifest, raw_path


def snapshot_binding(
    snapshot: SnapshotRecord, entry: SourceRegistryEntry, manifest: dict[str, Any]
) -> dict[str, Any]:
    return {
        "snapshot_record_id": snapshot.id,
        "source_document_id": snapshot.source_document_id,
        "source_id": snapshot.source_id,
        "source_url": snapshot.source_document.url,
        "raw_sha256": snapshot.content_hash,
        "storage_path": snapshot.storage_path,
        "captured_at": utc(snapshot.captured_at).isoformat(),
        "manifest_sha256": digest(canonical(manifest)),
        "registry_sha256": digest(canonical(entry.model_dump(mode="json"))),
    }


def extract_policy_clauses(product_code: str, html: str) -> list[dict[str, Any]]:
    """Require exact policy clauses, including the actual superscript exponent."""
    if product_code not in POLICY_PATHS:
        raise ValueError("unsupported policy product")
    soup = BeautifulSoup(html, "html.parser")
    matches: dict[str, list[dict[str, Any]]] = {}
    for index, paragraph in enumerate(soup.find_all("p")):
        text = paragraph.get_text(" ", strip=True)
        compact = "".join(text.split())
        if len(text) > 1400:
            continue
        kinds: list[tuple[str, dict[str, Any]]] = []
        if TAX_CLAUSE in compact:
            kinds.append(
                (
                    "tax",
                    {
                        "tax_included": False,
                        "tax_rate": None,
                        "customer_payable_tax": "unknown",
                        "condition": "unless_otherwise_noted",
                    },
                )
            )
        if product_code == "s3":
            if (
                "存储使用量以二进制(GB)计算，其中1GB等于230字节" in compact
                and "Gibibyte(GiB)" in compact
                and any(p.get_text(strip=True) == "30" for p in paragraph.find_all("sup"))
            ):
                kinds.append(
                    (
                        "storage_unit",
                        {
                            "raw_unit": "GB",
                            "canonical_unit": "GiB",
                            "bytes_per_unit": 1073741824,
                            "scope": "s3_storage_only",
                        },
                    )
                )
            if all(
                marker in compact
                for marker in ("S3存储桶中的存储对象", "一个月期间存储对象的时间", "S3Standard")
            ):
                kinds.append(
                    (
                        "storage_period",
                        {
                            "raw_period": "Mo",
                            "canonical_period": "month",
                            "hours_per_month": None,
                            "proration_rule": "unverified",
                        },
                    )
                )
            if all(
                marker in compact
                for marker in ("S3请求费用取决于请求类型，按请求数量计费", "PUT", "GET")
            ):
                kinds.append(
                    (
                        "request_unit",
                        {
                            "raw_unit": "Requests",
                            "canonical_unit": "request",
                            "catalog_price_denominator": 1,
                            "no_1000_request_multiplier": True,
                        },
                    )
                )
        elif all(
            marker in compact
            for marker in ("每个实例从启动到终止或停止使用", "以小时为单位", "Linux")
        ):
            kinds.append(
                (
                    "compute_unit",
                    {
                        "raw_unit": "Hrs",
                        "canonical_unit": "instance-hour",
                        "minimum_duration": "unverified",
                        "scope": "instance_elapsed_hours_not_month_estimate",
                    },
                )
            )
        for kind, policy in kinds:
            matches.setdefault(kind, []).append(
                {"kind": kind, "locator": f"html:p[{index}]", "clause": text, "policy": policy}
            )
    required = (
        ["tax", "storage_unit", "storage_period", "request_unit"]
        if product_code == "s3"
        else ["tax", "compute_unit"]
    )
    if any(kind not in matches for kind in required):
        raise ValueError("official tax/unit policy clause missing or ambiguous")
    return [
        min(matches[kind], key=lambda row: (len(row["clause"]), row["locator"]))
        for kind in required
    ]


def prepare_billing_policy(
    session: Session,
    snapshot_id: int,
    *,
    product_code: str,
    raw_root: Path,
    as_of: datetime,
    max_age_days: int = 7,
) -> dict[str, Any]:
    snapshot, entry, manifest, path = verified_snapshot(
        session, snapshot_id, raw_root=raw_root, as_of=as_of, max_age_days=max_age_days
    )
    route = POLICY_PATHS.get(product_code)
    urls = {f"https://aws.amazon.com/{route}", f"https://aws.amazon.com/cn/{route}"}
    if (
        route is None
        or snapshot.source_id != POLICY_SOURCES[product_code]
        or entry.product_code != product_code
        or entry.url not in urls
        or snapshot.source_document.url not in urls
        or snapshot.content_type != "text/html"
        or entry.robots_allowed is not True
        or entry.robots_checked_at is None
        or snapshot.content_length_bytes
        > min(16 * 1024 * 1024, entry.fetch_policy.max_content_length_bytes)
    ):
        raise ValueError("policy URL/product/collection scope mismatch")
    if snapshot.source_document.url != entry.url and (
        not entry.domain_policy.allow_redirects
        or "aws.amazon.com" not in entry.domain_policy.allowed_redirect_domains
    ):
        raise ValueError("language redirect is not authorized")
    raw = path.read_bytes()
    if digest(raw) != snapshot.content_hash or len(raw) != snapshot.content_length_bytes:
        raise ValueError("policy raw hash mismatch")
    binding = snapshot_binding(snapshot, entry, manifest)
    clauses = extract_policy_clauses(product_code, raw.decode("utf-8"))
    records = []
    for clause in clauses:
        payload = {
            **clause,
            **binding,
            "product_code": product_code,
            "market_mode": "international",
            "cloud_partition": "aws",
            "customer_eligible": False,
            "rule_version": RULE,
        }
        excerpt = canonical(payload)
        records.append(
            {
                "kind": clause["kind"],
                "locator": clause["locator"],
                "excerpt": excerpt,
                "content_hash": digest(excerpt),
                "parser_rule": RULE,
                "evidence_type": "html_section",
                **binding,
            }
        )
    return {
        "binding": binding,
        "records": records,
        "tax_status": "tax_excluded",
        "customer_payable_tax": "unknown",
        "tax_rate": None,
        "customer_eligible": False,
        "scope": "internal_reference_only",
    }


def evidence_row(
    session: Session, record: dict[str, Any], *, apply: bool = False
) -> Evidence | None:
    """Conflict-safe evidence upsert; caller owns transaction and commit."""
    rows = list(
        session.scalars(
            select(Evidence).where(
                Evidence.snapshot_record_id == record["snapshot_record_id"],
                Evidence.locator == record["locator"],
                Evidence.parser_rule == record["parser_rule"],
            )
        )
    )
    fields = {
        key: record[key]
        for key in (
            "source_document_id",
            "snapshot_record_id",
            "locator",
            "excerpt",
            "content_hash",
            "parser_rule",
            "evidence_type",
        )
    }
    if len(rows) > 1 or any(
        row.review_status == "rejected"
        or any(getattr(row, key) != value for key, value in fields.items())
        for row in rows
    ):
        raise ValueError("immutable evidence conflict or rejection")
    if rows:
        return rows[0]
    if not apply:
        return None
    row = Evidence(**fields, confidence=1.0, review_status="machine_extracted")
    session.add(row)
    session.flush()
    return row
