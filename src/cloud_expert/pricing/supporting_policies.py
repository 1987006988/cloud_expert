"""Extract narrowly scoped billing clauses from verified official raw snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing.extraction import _decode_payload

RULE = "supporting_price_policy_v1"
POLICY_SOURCES = (
    "huawei_cloud_basic_support_policy",
    "huawei_cloud_eip_binding_policy",
    "huawei_cloud_pricing_api_parameters",
    "aliyun_china_billing_tax_policy",
    "aliyun_basic_support_policy",
    "aliyun_ecs_fixed_ipv4_billing_policy",
)


def extract_clauses(source_id: str, html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    if source_id == "aliyun_ecs_fixed_ipv4_billing_policy":
        required = (
            "配置固定公网IP后，阿里云仅对出方向流量计费，入方向不计费。",
            "本文仅介绍固定公网IPv4的两种计费模式。",
            "按使用流量计费均按照实例实际使用的出网流量后付费。",
        )
        fixed_clauses = []
        for marker in required:
            fixed_matches = [
                p.get_text(" ", strip=True)
                for p in soup.find_all(["p", "blockquote"])
                if marker in "".join(p.get_text(" ", strip=True).split())
            ]
            if not fixed_matches:
                raise ValueError("fixed IPv4 billing scope clause is absent")
            fixed_clauses.append(min(fixed_matches, key=len))
        return [
            {
                "clauses": fixed_clauses,
                "ip_type": "instance_assigned_fixed_ipv4",
                "excludes": ["eip", "ipv6", "nat_gateway", "cdt_tariffs", "example_prices"],
                "price_basis": "separate_ip_holding_not_in_fixed_ipv4_billing",
            }
        ]
    terms = {
        "huawei_cloud_basic_support_policy": ["华为云支持计划基础级支持免费提供"],
        "huawei_cloud_eip_binding_policy": ["已绑定实例的按需计费的EIP不收取弹性公网IP保有费"],
        "huawei_cloud_pricing_api_parameters": ["15：Mbps", "17：GB"],
    }
    if source_id in terms:
        clauses = []
        for term in terms[source_id]:
            matches = {
                p.get_text(" ", strip=True)
                for p in soup.find_all(["p", "li"])
                if term in p.get_text(" ", strip=True) and len(p.get_text(" ", strip=True)) < 700
            }
            if not matches:
                raise ValueError("official policy clause is absent")
            clauses.append({"clause": min(matches, key=lambda s: (len(s), s))})
        return clauses
    if source_id not in POLICY_SOURCES:
        raise ValueError("unsupported policy source")
    for table in soup.find_all("table"):
        rows = [
            [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"], recursive=False)]
            for row in table.find_all("tr")
        ]
        if not rows:
            continue
        if source_id == "aliyun_china_billing_tax_policy":
            if len(rows[0]) < 3 or rows[0][1] != "阿里云中国站 (www.aliyun.com)":
                continue
            wanted = [row for row in rows[1:] if row and row[0] in {"交易货币", "价格说明"}]
            if len(wanted) == 2 and any(
                len(row) >= 3 and row[0] == "价格说明" and row[1] == "价格包含增值税。"
                for row in wanted
            ):
                return [{"headers": rows[0][:2], "rows": [r[:2] for r in wanted]}]
        elif (
            rows[0][:2] == ["Support Plan", "Basic"]
            and len(rows) > 1
            and rows[1][:2] == ["Billing standard", "Free"]
            and "CNY" in table.get_text(" ", strip=True)
        ):
            return [{"headers": rows[0][:2], "rows": [rows[1][:2]], "site_scope": "aliyun_china"}]
    raise ValueError("official policy table with explicit scope is absent")


def persist_policy_evidence(session: Session) -> list[dict[str, Any]]:
    results = []
    for source_id in POLICY_SOURCES:
        entry = get_entry_by_source_id(source_id)
        snapshot = session.scalar(
            select(SnapshotRecord).where(
                SnapshotRecord.source_id == source_id, SnapshotRecord.is_current.is_(True)
            )
        )
        if entry is None or entry.terms_review_status != "approved" or snapshot is None:
            raise ValueError("approved policy snapshot is missing")
        document = snapshot.source_document
        if (
            document.url != entry.url
            or document.provider.code != entry.provider_code
            or document.cloud_partition != entry.cloud_partition
            or document.content_hash != snapshot.content_hash
            or document.authority_level != "official_primary"
            or not document.is_current
        ):
            raise ValueError("policy source provenance is invalid")
        clauses = extract_clauses(source_id, _decode_payload(snapshot))
        ids = []
        for index, clause in enumerate(clauses):
            excerpt = json.dumps(clause, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(excerpt.encode()).hexdigest()
            locator = f"policy:{source_id}:clause[{index}]"
            row = session.scalar(
                select(Evidence).where(
                    Evidence.snapshot_record_id == snapshot.id,
                    Evidence.locator == locator,
                    Evidence.parser_rule == RULE,
                )
            )
            if row is None:
                row = Evidence(
                    source_document_id=document.id,
                    snapshot_record_id=snapshot.id,
                    locator=locator,
                    excerpt=excerpt,
                    content_hash=digest,
                    evidence_type="html_section",
                    parser_rule=RULE,
                    confidence=1.0,
                    review_status="machine_extracted",
                )
                session.add(row)
                session.flush()
            elif row.excerpt != excerpt or row.content_hash != digest:
                raise ValueError("existing immutable policy evidence differs")
            ids.append(row.id)
        results.append(
            {
                "source_id": source_id,
                "snapshot_record_id": snapshot.id,
                "evidence_ids": ids,
                "content_hash": snapshot.content_hash,
            }
        )
    session.commit()
    return results
