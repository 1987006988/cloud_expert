from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.enums import TaxStatus
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.market import MarketCompatibilityAssessment, MarketContext
from cloud_expert.database.models.region import Availability, Region
from cloud_expert.database.session import SessionLocal
from cloud_expert.market.scopes import RULE_VERSION, assess_compatibility, resolve_market_scope

REPORT_ROOT = Path("reports/market/reference_contexts")


def seed(*, apply: bool = False) -> dict[str, Any]:
    with SessionLocal() as session:
        regions = session.scalars(select(Region).order_by(Region.id)).all()
        partitions = session.scalars(select(CloudPartition).order_by(CloudPartition.id)).all()
        contexts: list[MarketContext] = []
        provenance: list[dict[str, Any]] = []
        for region in regions:
            if region.cloud_partition is None or region.country_code == "ZZ":
                raise ValueError(f"region {region.code} lacks validated market scope")
            evidence_ids = sorted(
                {
                    availability.evidence_id
                    for availability in session.scalars(
                        select(Availability).where(
                            Availability.region_id == region.id,
                            Availability.evidence_id.is_not(None),
                        )
                    )
                    if availability.evidence_id is not None
                }
            )
            if not evidence_ids:
                raise ValueError(f"region {region.code} has no availability evidence")
            context = MarketContext(
                context_code="pending",
                market_mode=region.market_mode,
                country_code=region.country_code,
                geography_code=region.country_code,
                preferred_region_codes=[region.code],
                provider_partition_codes=[region.cloud_partition.partition_code],
                target_currency=None,
                tax_context=TaxStatus.TAX_UNKNOWN.value,
                source_scope="region_availability_evidence",
                effective_at=datetime.now(UTC),
            )
            scope = resolve_market_scope(context)
            context.context_code = (
                f"reference_{region.cloud_partition.partition_code}_{region.code}_"
                f"{scope.fingerprint()[:8]}"
            )
            contexts.append(context)
            provenance.append(
                {
                    "context_code": context.context_code,
                    "region_id": region.id,
                    "evidence_ids": evidence_ids,
                }
            )
        for partition in partitions:
            if partition.partition_code != "huawei_cn":
                continue
            context = MarketContext(
                context_code="pending",
                market_mode="domestic",
                country_code="CN",
                geography_code="CN",
                preferred_region_codes=[],
                provider_partition_codes=[partition.partition_code],
                target_currency=None,
                tax_context=TaxStatus.TAX_UNKNOWN.value,
                source_scope="registry_partition_only_no_region_claim",
                effective_at=datetime.now(UTC),
            )
            context.context_code = (
                f"reference_huawei_cn_country_{resolve_market_scope(context).fingerprint()[:8]}"
            )
            contexts.append(context)
            provenance.append(
                {
                    "context_code": context.context_code,
                    "partition_id": partition.id,
                    "evidence_ids": [],
                    "limitation": "No Huawei Region availability claim is made.",
                }
            )
        contexts.sort(key=lambda item: item.context_code)
        existing_contexts = {
            row.context_code: row for row in session.scalars(select(MarketContext))
        }
        existing_assessments = {
            (row.left_fingerprint, row.right_fingerprint, row.rule_version)
            for row in session.scalars(select(MarketCompatibilityAssessment))
        }
        new_contexts = [
            context for context in contexts if context.context_code not in existing_contexts
        ]
        assessments: list[MarketCompatibilityAssessment] = []
        status_counts: Counter[str] = Counter()
        for left, right in combinations_with_replacement(contexts, 2):
            left_scope = resolve_market_scope(left)
            right_scope = resolve_market_scope(right)
            result = assess_compatibility(left_scope, right_scope, purpose="mapping")
            status_counts[result.status] += 1
            key = (left_scope.fingerprint(), right_scope.fingerprint(), RULE_VERSION)
            if key not in existing_assessments:
                assessments.append(
                    MarketCompatibilityAssessment(
                        left_fingerprint=key[0],
                        right_fingerprint=key[1],
                        rule_version=RULE_VERSION,
                        status=result.status,
                        reasons=list(result.reasons),
                        assessed_at=datetime.now(UTC),
                    )
                )
        digest = sha256(json.dumps(provenance, sort_keys=True).encode("utf-8")).hexdigest()
        summary: dict[str, Any] = {
            "input_fingerprint": digest,
            "reference_contexts": len(contexts),
            "new_contexts": len(new_contexts),
            "assessments": sum(status_counts.values()),
            "new_assessments": len(assessments),
            "status_counts": dict(status_counts),
            "customer_eligibility_granted": False,
            "applied": apply,
        }
        if not apply:
            return summary
        session.add_all(new_contexts)
        session.add_all(assessments)
        session.commit()
    report_dir = REPORT_ROOT / f"run_{digest[:12]}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation_results.json"
    if not report_path.exists():
        report_path.write_text(
            json.dumps({**summary, "provenance": provenance}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    summary["report_path"] = str(report_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = seed(apply=args.apply)
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
