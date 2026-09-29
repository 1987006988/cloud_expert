from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionRun
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.database.models.tco import CostCalculationRun, CostLineItem, TCOResult
from cloud_expert.database.session import SessionLocal
from cloud_expert.market.mapping_integrity import scan_mapping_market_integrity
from cloud_expert.market.validation import scan_market_integrity
from cloud_expert.pricing.freshness import price_snapshot_freshness

ROOT = Path(__file__).resolve().parents[1] / "reports" / "market" / "quality"


def build_report() -> dict[str, Any]:
    with SessionLocal() as session:
        partitions = list(session.scalars(select(CloudPartition).order_by(CloudPartition.id)))
        partition_modes = {
            (partition.provider_id, partition.partition_code): partition.market_mode
            for partition in partitions
        }
        sources: Counter[str] = Counter()
        for document in session.scalars(select(SourceDocument)):
            if document.cloud_partition is None:
                sources["unknown"] += 1
            else:
                sources[
                    partition_modes.get((document.provider_id, document.cloud_partition), "unknown")
                ] += 1
        regions = list(session.scalars(select(Region)))
        prices = list(session.scalars(select(PriceSnapshot)))
        price_market: Counter[str] = Counter()
        price_freshness: Counter[str] = Counter()
        for price in prices:
            price_market[price.price_sku.region.market_mode] += 1
            price_freshness[price_snapshot_freshness(price)] += 1
        current_tco_runs = select(func.max(CostCalculationRun.id)).group_by(
            CostCalculationRun.scenario_id
        )
        current_tco = list(
            session.scalars(select(TCOResult).where(TCOResult.run_id.in_(current_tco_runs)))
        )
        tco_market: Counter[str] = Counter(result.scenario.market_mode for result in current_tco)
        tco_completeness: Counter[str] = Counter(
            result.completeness_status for result in current_tco
        )
        fresh_complete_tco = 0
        for result in current_tco:
            if result.completeness_status != "complete":
                continue
            lines = list(
                session.scalars(
                    select(CostLineItem).where(
                        CostLineItem.run_id == result.run_id,
                        CostLineItem.provider_id == result.provider_id,
                        CostLineItem.product_id == result.product_id,
                    )
                )
            )
            if lines and all(
                line.amount is not None and price_snapshot_freshness(line.price_snapshot) == "fresh"
                for line in lines
            ):
                fresh_complete_tco += 1
        current_decision_runs = select(func.max(DecisionRun.id)).group_by(DecisionRun.scenario_id)
        current_decisions = list(
            session.scalars(
                select(CandidateDecisionResult).where(
                    CandidateDecisionResult.decision_run_id.in_(current_decision_runs)
                )
            )
        )
        decision_market: Counter[str] = Counter(
            result.decision_run.scenario.market_mode for result in current_decisions
        )
        decision_status: Counter[str] = Counter(
            result.decision_status for result in current_decisions
        )
        mapping = scan_mapping_market_integrity(session)
        integrity = scan_market_integrity(session)
        return {
            "provider_partitions": [
                {
                    "provider": partition.provider.code,
                    "partition": partition.partition_code,
                    "market_mode": partition.market_mode,
                }
                for partition in partitions
            ],
            "source_documents_by_market": dict(sources),
            "countries_with_regions": len({region.country_code for region in regions}),
            "regions": len(regions),
            "regions_with_unknown_country": sum(region.country_code == "ZZ" for region in regions),
            "mapping_status_counts": mapping["status_counts"],
            "mapping_active_scope_errors": mapping["active_errors"],
            "mapping_historical_scope_errors": len(mapping["issues"]) - mapping["active_errors"],
            "price_snapshots_by_market": dict(price_market),
            "price_freshness": dict(price_freshness),
            "current_tco_by_market": dict(tco_market),
            "current_tco_completeness": dict(tco_completeness),
            "current_tco_fresh_complete": fresh_complete_tco,
            "current_decisions_by_market": dict(decision_market),
            "current_decision_status": dict(decision_status),
            "current_customer_eligible_decisions": sum(
                result.customer_eligible for result in current_decisions
            ),
            "sales_artifact_status": "not_implemented",
            "integrity": integrity,
        }


def main() -> int:
    result = build_report()
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    fingerprint = sha256(serialized.encode("utf-8")).hexdigest()[:12]
    report_dir = ROOT / f"run_{fingerprint}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "market_results.json").write_text(serialized, encoding="utf-8")
    (report_dir / "market_summary.md").write_text(
        "# Market Quality Summary\n\n"
        f"- Partitions: {len(result['provider_partitions'])}\n"
        f"- Countries with recorded Regions: {result['countries_with_regions']}\n"
        f"- Regions: {result['regions']}\n"
        f"- Active mapping scope errors: {result['mapping_active_scope_errors']}\n"
        f"- Historical mapping scope errors: {result['mapping_historical_scope_errors']}\n"
        f"- Current customer-eligible decisions: {result['current_customer_eligible_decisions']}\n"
        f"- Price freshness: `{result['price_freshness']}`\n"
        f"- Current TCO with complete, fresh price lines: {result['current_tco_fresh_complete']}\n"
        f"- Sales artifact chain: `{result['sales_artifact_status']}`\n",
        encoding="utf-8",
    )
    print(json.dumps({"report_dir": str(report_dir), **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
