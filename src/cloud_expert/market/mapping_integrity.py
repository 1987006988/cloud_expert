from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.product import SKU, Product
from cloud_expert.database.models.product_extension import ProductFamily, ServiceTier

INACTIVE_STATUSES = {"rejected", "superseded"}


def relationship_market_status(source_mode: str, target_mode: str, rule_mode: str) -> str:
    if source_mode not in {"domestic", "international"} or target_mode not in {
        "domestic",
        "international",
    }:
        return "unknown"
    if source_mode != target_mode:
        return "cross_market" if rule_mode == "cross_market" else "mislabeled_cross_market"
    return "compatible" if rule_mode == source_mode else "rule_market_mismatch"


def _entity_product(session: Session, entity_type: str, entity_id: int) -> Product | None:
    if entity_type == "product":
        return session.get(Product, entity_id)
    if entity_type == "product_family":
        family = session.get(ProductFamily, entity_id)
        return family.product if family is not None else None
    if entity_type == "sku":
        sku = session.get(SKU, entity_id)
        return sku.product if sku is not None else None
    if entity_type == "service_tier":
        tier = session.get(ServiceTier, entity_id)
        return tier.product if tier is not None else None
    return None


def scan_mapping_market_integrity(session: Session) -> dict[str, Any]:
    partitions = {
        (partition.provider_id, partition.partition_code): partition
        for partition in session.scalars(select(CloudPartition))
    }
    statuses: Counter[str] = Counter()
    issues: list[dict[str, Any]] = []
    active_errors = 0
    for candidate in session.scalars(select(MappingCandidate).order_by(MappingCandidate.id)):
        source = _entity_product(session, candidate.source_entity_type, candidate.source_entity_id)
        target = _entity_product(session, candidate.target_entity_type, candidate.target_entity_id)
        reasons: set[str] = set()
        if source is None or target is None:
            status = "unknown"
            reasons.add("mapping_entity_unresolved")
        else:
            status = relationship_market_status(
                source.market_mode, target.market_mode, candidate.rule_set.market_mode
            )
            if status not in {"compatible", "cross_market"}:
                reasons.add(status)
            if source.provider_id != candidate.source_provider_id:
                reasons.add("source_provider_mismatch")
            if target.provider_id != candidate.target_provider_id:
                reasons.add("target_provider_mismatch")
            for link in candidate.evidence_links:
                document = link.evidence.source_document
                if link.evidence_role == "source_field":
                    expected = source
                elif link.evidence_role == "target_field":
                    expected = target
                elif document.provider_id == source.provider_id:
                    expected = source
                elif document.provider_id == target.provider_id:
                    expected = target
                else:
                    reasons.add("evidence_provider_unrelated")
                    continue
                if document.provider_id != expected.provider_id:
                    reasons.add("evidence_provider_mismatch")
                if document.cloud_partition is None:
                    reasons.add("evidence_partition_missing")
                    continue
                partition = partitions.get((document.provider_id, document.cloud_partition))
                if partition is None:
                    reasons.add("evidence_partition_unregistered")
                elif partition.market_mode != expected.market_mode:
                    reasons.add("evidence_partition_market_mismatch")
        statuses[status] += 1
        if reasons:
            active = candidate.candidate_status not in INACTIVE_STATUSES
            active_errors += int(active)
            issues.append(
                {
                    "candidate_id": candidate.id,
                    "active": active,
                    "status": status,
                    "reasons": sorted(reasons),
                }
            )
    return {
        "total": sum(statuses.values()),
        "status_counts": dict(statuses),
        "active_errors": active_errors,
        "issues": issues,
        "valid": active_errors == 0,
        "limitation": "Product market mode and linked evidence partitions are checked; SKU or tier availability by Region is separate.",
    }
