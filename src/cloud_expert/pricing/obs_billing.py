"""Versioned OBS billing clauses, explicitly not a price tariff or API unit proof."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.config.settings import get_settings
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.pricing.huawei_promotion import _get_or_create_evidence, _raw

SOURCE_ID = "huawei_cloud_obs_billing_period_policy"
RULE = "obs_billing_policy_clauses_v1"
CLAUSES = {
    "hourly_settlement": "以小时为单位，每小时整点结算",
    "minimum_billed_hour": "费用结算的最小时长为1小时",
    "monthly_to_hourly_example": "如果需要计算每小时产生的费用",
}


def extract_billing_clauses(html: str) -> list[dict[str, Any]]:
    paragraphs = [
        p.get_text(" ", strip=True) for p in BeautifulSoup(html, "html.parser").find_all("p")
    ]
    rows: list[dict[str, Any]] = []
    for code, marker in CLAUSES.items():
        matches = [text for text in paragraphs if marker in text and len(text) < 1200]
        if not matches:
            raise ValueError(f"Required official billing clause is missing: {code}")
        clause = min(matches, key=lambda text: (len(text), text))
        if code == "monthly_to_hourly_example" and not all(
            token in clause for token in ("1/24", "1/30", "仅供参考")
        ):
            raise ValueError("Example conversion lost its period or non-tariff disclaimer")
        rows.append(
            {
                "clause_code": code,
                "clause": clause,
                "scope": "huawei_cn_obs_billing_policy",
                "not_current_price_tariff": True,
                "api_size_quote_time_basis_proven": False,
            }
        )
    return rows


def persist_billing_clauses(session: Session, *, root: Path | None = None) -> dict[str, Any]:
    """Caller owns the transaction; existing immutable evidence is never overwritten."""
    root = (root or Path(get_settings().raw_data_dir)).resolve()
    snapshot = session.scalar(
        select(SnapshotRecord).where(
            SnapshotRecord.source_id == SOURCE_ID, SnapshotRecord.is_current.is_(True)
        )
    )
    if snapshot is None:
        raise ValueError("Registered OBS billing policy has no current snapshot")
    raw = _raw(session, snapshot, root)
    rows = extract_billing_clauses(raw.decode("utf-8"))
    evidence: list[Evidence] = []
    for row in rows:
        excerpt = json.dumps(row, ensure_ascii=False, sort_keys=True)
        evidence.append(
            _get_or_create_evidence(
                session, snapshot, f"policy:{SOURCE_ID}:{row['clause_code']}", excerpt, RULE
            )
        )
    return {
        "source_document_id": snapshot.source_document_id,
        "snapshot_record_id": snapshot.id,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_ids": [item.id for item in evidence],
        "price_snapshots_created": 0,
        "api_size_quote_time_basis_proven": False,
    }
