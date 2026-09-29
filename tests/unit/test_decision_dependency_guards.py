from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from cloud_expert.database.models.decision import DecisionScenario, ScoringPolicy
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate, MappingRuleSet
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.tco import PricingScenario, TCOResult
from cloud_expert.decision.pipeline import (
    _candidate_query,
    _run_code,
    _status_from_candidate,
    _tco_matches_scenario,
)
from cloud_expert.pricing.freshness import price_snapshot_freshness


def test_product_candidate_query_respects_workload_category(session: Session) -> None:
    compute = ProductCategory(code="compute", name="Compute")
    storage = ProductCategory(code="object_storage", name="Object Storage")
    source = Provider(code="a", name="A", display_name="A")
    target = Provider(code="b", name="B", display_name="B")
    session.add_all([compute, storage, source, target])
    session.flush()
    compute_products = [
        Product(
            provider_id=provider.id,
            category_id=compute.id,
            market_mode="international",
            code="compute",
            official_name="Compute",
            display_name="Compute",
        )
        for provider in (source, target)
    ]
    storage_products = [
        Product(
            provider_id=provider.id,
            category_id=storage.id,
            market_mode="international",
            code="storage",
            official_name="Storage",
            display_name="Storage",
        )
        for provider in (source, target)
    ]
    rule = MappingRuleSet(
        rule_set_code="products",
        rule_set_version="v1",
        mapping_level="product",
        category="all",
        market_mode="cross_market",
        status="active",
    )
    session.add_all([*compute_products, *storage_products, rule])
    session.flush()
    for pair in (compute_products, storage_products):
        session.add(
            MappingCandidate(
                mapping_level="product",
                source_provider_id=source.id,
                source_entity_type="product",
                source_entity_id=pair[0].id,
                target_provider_id=target.id,
                target_entity_type="product",
                target_entity_id=pair[1].id,
                relationship_type="close_alternative",
                candidate_status="candidate",
                rule_set_id=rule.id,
                explanation="synthetic",
                generated_at=datetime.now(UTC),
                review_status="pending_review",
            )
        )
    session.flush()
    compute_scenario = DecisionScenario(workload_profile={"category": "compute"})
    storage_scenario = DecisionScenario(workload_profile={"category": "object_storage"})
    compute_ids = session.scalars(_candidate_query(compute_scenario)).all()
    storage_ids = session.scalars(_candidate_query(storage_scenario)).all()
    assert len(compute_ids) == len(storage_ids) == 1
    assert session.get(Product, compute_ids[0].source_entity_id).category.code == "compute"
    assert session.get(Product, storage_ids[0].source_entity_id).category.code == "object_storage"
    compute_ids[0].candidate_status = "superseded"
    session.flush()
    assert session.scalars(_candidate_query(compute_scenario)).all() == []


def test_stale_price_is_not_fresh_tco_or_eligible_cost() -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    snapshot = PriceSnapshot(captured_at=now - timedelta(days=60))
    assert price_snapshot_freshness(snapshot, now=now) == "stale"
    candidate = MappingCandidate(candidate_status="candidate", review_status="human_reviewed")
    package = EvidencePackage(evidence_completeness=1, customer_eligible=True)
    tco = TCOResult(completeness_status="complete", freshness_status="stale")
    scenario = DecisionScenario(workload_profile={"cost_required": True})
    assert (
        _status_from_candidate(
            candidate=candidate, package=package, tco=tco, hard_blocks=[], scenario=scenario
        )
        == "incomplete_cost"
    )


def test_decision_run_identity_changes_with_dependency_hash() -> None:
    scenario = DecisionScenario(scenario_code="test", scenario_version="v1")
    policy = ScoringPolicy(policy_code="policy", policy_version="v1")
    cutoff = datetime(2026, 9, 29, tzinfo=UTC)
    assert _run_code(scenario, policy, cutoff, "a" * 64) != _run_code(
        scenario, policy, cutoff, "b" * 64
    )


def test_tco_missing_required_request_and_traffic_usage_is_rejected() -> None:
    pricing = PricingScenario(workload_profile={"storage_gb_month": "1024"})
    tco = TCOResult(scenario=pricing, completeness_status="complete", freshness_status="fresh")
    decision = DecisionScenario(
        workload_profile={
            "storage_gb_month": 1024,
            "requests_per_month": 100000,
            "outbound_gb": 100,
        }
    )
    assert _tco_matches_scenario(None, tco, decision) is False


def test_unknown_workload_category_is_not_broad_query() -> None:
    with pytest.raises(ValueError, match="unsupported decision workload category"):
        _candidate_query(DecisionScenario(workload_profile={}))
