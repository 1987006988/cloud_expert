from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionRun
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate, MappingRuleSet
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.database.models.tco import CostCalculationRun, PricingScenario, TCOResult
from cloud_expert.market.mapping_integrity import scan_mapping_market_integrity


def scan_market_integrity(session: Session) -> dict[str, Any]:
    def count(query: Any) -> int:
        return int(session.scalar(query) or 0)

    source_partition_missing = count(
        select(func.count())
        .select_from(SourceDocument)
        .where(SourceDocument.cloud_partition.is_(None))
    )
    region_partition_missing = count(
        select(func.count()).select_from(Region).where(Region.cloud_partition_id.is_(None))
    )
    region_country_unknown = count(
        select(func.count()).select_from(Region).where(Region.country_code == "ZZ")
    )
    cross_market_mappings = count(
        select(func.count())
        .select_from(MappingCandidate)
        .join(MappingRuleSet, MappingCandidate.rule_set_id == MappingRuleSet.id)
        .where(
            MappingRuleSet.market_mode == "cross_market",
            MappingCandidate.candidate_status.not_in(["rejected", "superseded"]),
        )
    )
    all_cross_market_mappings = count(
        select(func.count())
        .select_from(MappingCandidate)
        .join(MappingRuleSet, MappingCandidate.rule_set_id == MappingRuleSet.id)
        .where(MappingRuleSet.market_mode == "cross_market")
    )
    latest_decision_runs = select(func.max(DecisionRun.id)).group_by(DecisionRun.scenario_id)
    cross_market_decisions = count(
        select(func.count())
        .select_from(CandidateDecisionResult)
        .join(MappingCandidate, CandidateDecisionResult.mapping_candidate_id == MappingCandidate.id)
        .join(MappingRuleSet, MappingCandidate.rule_set_id == MappingRuleSet.id)
        .where(
            CandidateDecisionResult.decision_run_id.in_(latest_decision_runs),
            MappingRuleSet.market_mode == "cross_market",
            MappingCandidate.candidate_status.not_in(["rejected", "superseded"]),
        )
    )
    all_cross_market_decisions = count(
        select(func.count())
        .select_from(CandidateDecisionResult)
        .join(MappingCandidate, CandidateDecisionResult.mapping_candidate_id == MappingCandidate.id)
        .join(MappingRuleSet, MappingCandidate.rule_set_id == MappingRuleSet.id)
        .where(MappingRuleSet.market_mode == "cross_market")
    )
    customer_cross_market_packages = count(
        select(func.count())
        .select_from(EvidencePackage)
        .where(
            EvidencePackage.market_mode == "cross_market",
            EvidencePackage.customer_eligible.is_(True),
        )
    )
    customer_cross_market_decisions = count(
        select(func.count())
        .select_from(CandidateDecisionResult)
        .join(MappingCandidate, CandidateDecisionResult.mapping_candidate_id == MappingCandidate.id)
        .join(MappingRuleSet, MappingCandidate.rule_set_id == MappingRuleSet.id)
        .where(
            MappingRuleSet.market_mode == "cross_market",
            CandidateDecisionResult.customer_eligible.is_(True),
        )
    )
    latest_tco_runs = select(func.max(CostCalculationRun.id)).group_by(
        CostCalculationRun.scenario_id
    )
    all_tco_product_market_mismatch = count(
        select(func.count())
        .select_from(TCOResult)
        .join(PricingScenario, TCOResult.scenario_id == PricingScenario.id)
        .join(Product, TCOResult.product_id == Product.id)
        .where(PricingScenario.market_mode != Product.market_mode)
    )
    tco_product_market_mismatch = count(
        select(func.count())
        .select_from(TCOResult)
        .join(PricingScenario, TCOResult.scenario_id == PricingScenario.id)
        .join(Product, TCOResult.product_id == Product.id)
        .where(
            TCOResult.run_id.in_(latest_tco_runs),
            PricingScenario.market_mode != Product.market_mode,
        )
    )
    price_issues = {
        "price_region_partition_missing": 0,
        "price_product_region_market_mismatch": 0,
        "price_evidence_partition_mismatch": 0,
        "price_evidence_partition_missing": 0,
    }
    for snapshot in session.scalars(select(PriceSnapshot)).all():
        price_sku: PriceSKU = snapshot.price_sku
        region = price_sku.region
        if region.cloud_partition_id is None:
            price_issues["price_region_partition_missing"] += 1
        if price_sku.product.market_mode != region.market_mode:
            price_issues["price_product_region_market_mismatch"] += 1
        source_partition = snapshot.evidence.source_document.cloud_partition
        region_partition = region.cloud_partition.partition_code if region.cloud_partition else None
        if source_partition is None:
            price_issues["price_evidence_partition_missing"] += 1
        elif region_partition and source_partition != region_partition:
            price_issues["price_evidence_partition_mismatch"] += 1
    mapping_integrity = scan_mapping_market_integrity(session)
    counts = {
        "source_partition_missing": source_partition_missing,
        "region_partition_missing": region_partition_missing,
        "region_country_unknown": region_country_unknown,
        "cross_market_mappings": cross_market_mappings,
        "historical_cross_market_mappings": all_cross_market_mappings - cross_market_mappings,
        "cross_market_decisions_internal": cross_market_decisions,
        "historical_cross_market_decisions": all_cross_market_decisions - cross_market_decisions,
        "active_mapping_scope_errors": mapping_integrity["active_errors"],
        "historical_mapping_scope_errors": len(mapping_integrity["issues"])
        - mapping_integrity["active_errors"],
        "customer_cross_market_packages": customer_cross_market_packages,
        "customer_cross_market_decisions": customer_cross_market_decisions,
        "tco_product_market_mismatch": tco_product_market_mismatch,
        "historical_tco_product_market_mismatch": all_tco_product_market_mismatch
        - tco_product_market_mismatch,
        **price_issues,
    }
    return {
        "counts": counts,
        "customer_exposure_detected": bool(
            customer_cross_market_packages or customer_cross_market_decisions
        ),
        "internal_remediation_required": bool(
            source_partition_missing
            or region_partition_missing
            or region_country_unknown
            or mapping_integrity["active_errors"]
            or tco_product_market_mismatch
            or all_tco_product_market_mismatch - tco_product_market_mismatch
            or any(price_issues.values())
        ),
    }
