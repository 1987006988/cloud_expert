"""Evidence-backed zero fees, not price snapshots or model approvals."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.config.settings import get_settings
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing.supporting_policies import RULE as EXTRACTION_RULE
from cloud_expert.pricing.supporting_policies import extract_clauses

RULE_VERSION = "scoped_zero_cost_policy_v1"
POLICIES = {
    "huawei_basic_support": (
        "huawei_cloud_basic_support_policy",
        "huawei_cloud",
        "huawei_cn",
        "support",
    ),
    "huawei_bound_eip": (
        "huawei_cloud_eip_binding_policy",
        "huawei_cloud",
        "huawei_cn",
        "ip_holding",
    ),
    "aliyun_basic_support": (
        "aliyun_basic_support_policy",
        "aliyun",
        "aliyun_public_cn",
        "support",
    ),
    "aliyun_instance_fixed_ipv4": (
        "aliyun_ecs_fixed_ipv4_billing_policy",
        "aliyun",
        "aliyun_public_cn",
        "ip_holding",
    ),
}


class PolicyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    provider_code: Literal["huawei_cloud", "aliyun"]
    partition: Literal["huawei_cn", "aliyun_public_cn"]
    region: str = Field(min_length=1)
    market_mode: Literal["domestic"] = "domestic"
    country_code: Literal["CN"] = "CN"
    currency: Literal["CNY"] = "CNY"
    billing_mode: Literal["on_demand"] = "on_demand"
    duration_hours: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    support_plan: Literal["basic", "paid", "unknown"]
    eip_binding: Literal["bound", "unbound", "not_deployed", "unknown"]
    eip_bound_hours: Decimal = Field(ge=0, max_digits=24, decimal_places=8)

    @model_validator(mode="after")
    def check_duration(self) -> PolicyContext:
        if self.eip_bound_hours > self.duration_hours:
            raise ValueError("bound hours exceed the explicit scenario period")
        if self.eip_binding != "bound" and self.eip_bound_hours != 0:
            raise ValueError("non-bound EIP cannot have bound hours")
        return self


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_zero_cost_policy(
    session: Session,
    *,
    policy_code: str,
    evidence_id: int,
    context: PolicyContext,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a pinned receipt after re-reading raw evidence; never change the DB.

    A current snapshot must also be at most 30 days old. This conservative local
    consumption limit is not a claim about the provider's policy validity term.
    """
    with session.no_autoflush:
        return _validate_policy(
            session,
            policy_code=policy_code,
            evidence_id=evidence_id,
            context=context,
            root=root,
            now=now,
        )


def _validate_policy(
    session: Session,
    *,
    policy_code: str,
    evidence_id: int,
    context: PolicyContext,
    root: Path | None,
    now: datetime | None,
) -> dict[str, Any]:
    context = PolicyContext.model_validate(context.model_dump())
    definition = POLICIES.get(policy_code)
    if definition is None:
        raise ValueError("unsupported zero-cost policy")
    source_id, provider, partition, dimension = definition
    if (context.provider_code, context.partition) != (provider, partition):
        raise ValueError("policy provider/partition mismatch")
    if dimension == "support" and context.support_plan != "basic":
        raise ValueError("free support only applies to the basic plan")
    if policy_code == "aliyun_instance_fixed_ipv4" and context.eip_binding != "not_deployed":
        raise ValueError("instance fixed IPv4 policy cannot apply to an independent EIP")
    if policy_code == "huawei_bound_eip" and (
        context.eip_binding != "bound" or context.eip_bound_hours != context.duration_hours
    ):
        raise ValueError("EIP must stay bound for the entire priced period")
    product = session.get(Product, context.product_id)
    if (
        product is None
        or product.provider_id != context.provider_id
        or product.provider.code != provider
        or product.code != "ecs"
        or product.market_mode != "domestic"
    ):
        raise ValueError("policy product scope is invalid")
    region = session.scalar(
        select(Region).where(
            Region.provider_id == context.provider_id, Region.code == context.region
        )
    )
    if (
        region is None
        or region.country_code != "CN"
        or region.market_mode != "domestic"
        or region.cloud_partition is None
        or region.cloud_partition.partition_code != partition
        or region.cloud_partition.provider_id != context.provider_id
    ):
        raise ValueError("policy region scope is invalid")
    evidence = session.get(Evidence, evidence_id)
    if (
        evidence is None
        or evidence.review_status == "rejected"
        or evidence.parser_rule != EXTRACTION_RULE
        or evidence.content_hash != _sha(evidence.excerpt.encode("utf-8"))
        or evidence.snapshot_record_id is None
    ):
        raise ValueError("policy evidence is missing, rejected or altered")
    snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
    entry = get_entry_by_source_id(source_id)
    if snapshot is None or entry is None:
        raise ValueError("official policy source is missing")
    document = snapshot.source_document
    current = _utc(now or datetime.now(UTC))
    captured = _utc(snapshot.captured_at)
    if (
        snapshot.source_id != source_id
        or snapshot.source_document_id != evidence.source_document_id
        or not snapshot.is_current
        or not document.is_current
        or not entry.enabled
        or entry.terms_review_status != "approved"
        or entry.authority_level != "official_primary"
        or entry.source_type != "documentation"
        or entry.provider_code != provider
        or entry.cloud_partition != partition
        or entry.market_mode != "domestic"
        or document.source_type != "documentation"
        or document.authority_level != "official_primary"
        or document.provider_id != context.provider_id
        or document.cloud_partition != partition
        or document.url != entry.url
        or document.content_hash != snapshot.content_hash
        or captured > current
        or current - captured > timedelta(days=30)
    ):
        raise ValueError("policy provenance is invalid or no longer current")
    base = (root or Path(get_settings().raw_data_dir)).resolve()
    raw_path = (base / snapshot.storage_path).resolve()
    manifest_path = (base / snapshot.manifest_path).resolve()
    if not raw_path.is_relative_to(base) or not manifest_path.is_relative_to(base):
        raise ValueError("policy snapshot path escapes raw storage")
    raw = raw_path.read_bytes()
    manifest = SnapshotStore(base).load_manifest(manifest_path)
    if (
        _sha(raw) != snapshot.content_hash
        or len(raw) != snapshot.content_length_bytes
        or manifest.content_sha256 != snapshot.content_hash
        or manifest.content_length_bytes != len(raw)
        or manifest.storage_path != snapshot.storage_path
        or manifest.source_id != source_id
        or manifest.provider_code != provider
        or manifest.market_mode != "domestic"
        or manifest.source_type != "documentation"
        or manifest.requested_url != entry.url
        or manifest.http_status != 200
        or manifest.content_type.split(";", 1)[0] != "text/html"
        or _utc(manifest.captured_at) != captured
    ):
        raise ValueError("policy raw/manifest hash or scope mismatch")
    clauses = extract_clauses(source_id, raw.decode(entry.expected_encoding or "utf-8"))
    if json.loads(evidence.excerpt) not in clauses:
        raise ValueError("policy excerpt does not match the raw official clause")
    return {
        "rule_version": RULE_VERSION,
        "policy_code": policy_code,
        "dimension": dimension,
        "evidence_id": evidence.id,
        "evidence_sha256": evidence.content_hash,
        "source_document_id": document.id,
        "snapshot_record_id": snapshot.id,
        "raw_sha256": snapshot.content_hash,
        "manifest_sha256": _sha(manifest_path.read_bytes()),
        "captured_at": captured.isoformat(),
        "conditions": context.model_dump(mode="json"),
        "amount": "0",
        "currency": "CNY",
        "only_dimension": dimension,
        "price_snapshot_created": False,
        "model_approved": False,
        "customer_eligible": False,
    }
