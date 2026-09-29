from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    ConfidenceLevel,
    DecisionOutputLevel,
    DecisionReviewStatus,
    DecisionRunStatus,
    DecisionStatus,
    DimensionScoreStatus,
    FreshnessStatus,
    MappingCandidateStatus,
    ReviewStatus,
    RuleEvaluationStatus,
    ScoringDimension,
    TCOCompletenessStatus,
)
from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.decision import (
    CandidateDecisionResult,
    DecisionRun,
    DecisionScenario,
    DecisionSensitivityResult,
    DimensionScore,
    RuleEvaluation,
    ScenarioRequirement,
    ScoringPolicy,
    ScoringRule,
)
from cloud_expert.database.models.evidence_package import EvidencePackage, EvidencePackageItem
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingFieldComparison,
    MappingRuleSet,
)
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import SKU, Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.tco import CostLineItem, PricingScenario, TCOResult
from cloud_expert.decision.config import (
    PolicyConfig,
    ScenarioConfig,
    load_policy_config,
    load_scenario_config,
)
from cloud_expert.decision.dependency_state import current_source_state, implementation_state
from cloud_expert.decision.policy_rules import evaluate_policy_rule
from cloud_expert.decision.requirements import evaluate_scenario_requirements
from cloud_expert.decision.sensitivity import analyze_weight_sensitivity
from cloud_expert.model_review.approvals import mapping_approval
from cloud_expert.pricing.freshness import price_snapshot_freshness
from cloud_expert.pricing.tco import tco_result_currently_complete

REPORT_DIR = Path("reports") / "decision"
REVIEW_SAMPLE_PATH = Path("reports") / "review_samples" / "week10_decision_review.csv"
Q = Decimal("0.0001")
ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")
ENGINE_VERSION = "week14_decision_verified_requirements_v5"


@dataclass(frozen=True)
class RunSummary:
    run_code: str
    scenario_code: str
    scenario_version: str
    status: str
    candidate_count: int
    eligible_count: int
    blocked_count: int
    review_count: int
    warning_count: int
    created: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _decimal(value: Decimal | int | str | None, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    return Decimal(str(value)).quantize(Q)


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _weights(policy: ScoringPolicy) -> dict[str, Decimal]:
    return {key: _decimal(value) for key, value in policy.dimension_weights.items()}


def _latest_price_cutoff(session: Session) -> datetime:
    cutoff = session.scalar(select(func.max(TCOResult.created_at)))
    return cutoff or _now()


def upsert_policy(session: Session, config: PolicyConfig) -> ScoringPolicy:
    policy = session.scalar(
        select(ScoringPolicy).where(
            ScoringPolicy.policy_code == config.code,
            ScoringPolicy.policy_version == config.version,
        )
    )
    if policy is None:
        policy = ScoringPolicy(
            policy_code=config.code,
            policy_version=config.version,
            scenario_type=config.scenario_type.value,
            description=config.description,
            dimension_weights={key: str(value) for key, value in config.weights.items()},
            hard_block_rules=config.hard_blocks,
            missing_data_policy=config.missing_data_policy,
            confidence_policy=config.confidence_policy,
            thresholds=config.thresholds,
            effective_from=datetime.fromisoformat(config.effective_from),
            status=config.status.value,
        )
        session.add(policy)
        session.flush()
    for rule_config in config.rules:
        existing = session.scalar(
            select(ScoringRule).where(
                ScoringRule.policy_id == policy.id,
                ScoringRule.rule_code == rule_config.code,
                ScoringRule.rule_version == rule_config.version,
            )
        )
        if existing is None:
            session.add(
                ScoringRule(
                    policy_id=policy.id,
                    rule_code=rule_config.code,
                    rule_version=rule_config.version,
                    dimension=rule_config.dimension.value,
                    operator=rule_config.operator.value,
                    expected_value=rule_config.expected_value,
                    minimum_score=rule_config.minimum_score,
                    maximum_score=rule_config.maximum_score,
                    score_function=rule_config.score_function.value,
                    conditions=rule_config.conditions,
                    evidence_requirement=rule_config.evidence_requirement,
                    missing_data_policy=rule_config.missing_data_policy.value,
                    priority=rule_config.priority.value,
                    status=rule_config.status.value,
                )
            )
    session.flush()
    return policy


def upsert_scenario(
    session: Session, config: ScenarioConfig, policy: ScoringPolicy
) -> DecisionScenario:
    scenario = session.scalar(
        select(DecisionScenario).where(
            DecisionScenario.scenario_code == config.code,
            DecisionScenario.scenario_version == config.version,
        )
    )
    if scenario is None:
        scenario = DecisionScenario(
            scenario_code=config.code,
            scenario_version=config.version,
            name=config.name,
            description=config.description,
            scenario_type=config.scenario_type.value,
            market_mode=config.market_mode.value,
            industry=config.industry,
            country_code=config.country_code,
            preferred_regions=config.preferred_regions,
            workload_profile=config.workload_profile,
            technical_requirements=config.technical_requirements,
            availability_requirements=config.availability_requirements,
            compliance_requirements=config.compliance_requirements,
            data_residency_requirements=config.data_residency_requirements,
            operational_requirements=config.operational_requirements,
            migration_requirements=config.migration_requirements,
            budget_preferences=config.budget_preferences,
            scoring_policy_id=policy.id,
            status=config.status.value,
            effective_from=datetime.fromisoformat(config.effective_from),
        )
        session.add(scenario)
        session.flush()
    for requirement_config in config.requirements:
        existing = session.scalar(
            select(ScenarioRequirement).where(
                ScenarioRequirement.scenario_id == scenario.id,
                ScenarioRequirement.requirement_code == requirement_config.code,
            )
        )
        if existing is None:
            session.add(
                ScenarioRequirement(
                    scenario_id=scenario.id,
                    requirement_code=requirement_config.code,
                    requirement_type=requirement_config.requirement_type.value,
                    operator=requirement_config.operator.value,
                    required_value=requirement_config.required_value,
                    unit=requirement_config.unit,
                    qualifier=requirement_config.qualifier,
                    scope=requirement_config.scope,
                    priority=requirement_config.priority.value,
                    is_mandatory=requirement_config.is_mandatory,
                    missing_data_policy=requirement_config.missing_data_policy.value,
                    evidence_requirement=requirement_config.evidence_requirement,
                )
            )
    session.flush()
    return scenario


def create_from_config(session: Session, scenario_path: Path) -> DecisionScenario:
    scenario_config = load_scenario_config(scenario_path)
    policy_path = (
        Path("config") / "decision" / "policies" / f"{scenario_config.scoring_policy_code}.yaml"
    )
    policy_config = load_policy_config(policy_path)
    policy = upsert_policy(session, policy_config)
    scenario = upsert_scenario(session, scenario_config, policy)
    session.commit()
    return scenario


def _candidate_query(scenario: DecisionScenario) -> Select[tuple[MappingCandidate]]:
    levels = {"product", "sku", "product_family", "service_tier"}
    category = str(scenario.workload_profile.get("category", ""))
    if category not in {"compute", "object_storage"}:
        raise ValueError(f"unsupported decision workload category: {category or '<missing>'}")
    statement = select(MappingCandidate).where(
        MappingCandidate.mapping_level.in_(levels),
        MappingCandidate.candidate_status.not_in(
            [MappingCandidateStatus.REJECTED.value, MappingCandidateStatus.SUPERSEDED.value]
        ),
    )
    if category == "compute":
        statement = statement.where(
            MappingCandidate.mapping_level.in_({"product", "sku", "product_family"})
        )
    if category == "object_storage":
        statement = statement.where(MappingCandidate.mapping_level.in_({"product", "service_tier"}))
    if category in {"compute", "object_storage"}:
        matching_product_ids = (
            select(Product.id)
            .join(ProductCategory, Product.category_id == ProductCategory.id)
            .where(ProductCategory.code == category)
        )
        statement = statement.where(
            or_(
                and_(
                    MappingCandidate.mapping_level != "product",
                    MappingCandidate.rule_set.has(MappingRuleSet.category == category),
                ),
                and_(
                    MappingCandidate.mapping_level == "product",
                    MappingCandidate.source_entity_type == "product",
                    MappingCandidate.target_entity_type == "product",
                    MappingCandidate.source_entity_id.in_(matching_product_ids),
                    MappingCandidate.target_entity_id.in_(matching_product_ids),
                ),
            )
        )
    return statement.order_by(MappingCandidate.id)


def _product_for_candidate(session: Session, candidate: MappingCandidate) -> Product | None:
    entity_id = candidate.target_entity_id
    if candidate.target_entity_type == "sku":
        sku = session.get(SKU, entity_id)
        return sku.product if sku else None
    if candidate.target_entity_type != "product":
        return None
    return session.get(Product, entity_id)


def _latest_package(session: Session, candidate: MappingCandidate) -> EvidencePackage | None:
    return session.scalar(
        select(EvidencePackage)
        .where(EvidencePackage.mapping_candidate_id == candidate.id)
        .order_by(EvidencePackage.generated_at.desc(), EvidencePackage.id.desc())
    )


def _latest_tco(
    session: Session, candidate: MappingCandidate, scenario: DecisionScenario
) -> TCOResult | None:
    if candidate.target_entity_type != "product":
        return None
    results = session.scalars(
        select(TCOResult)
        .where(
            TCOResult.provider_id == candidate.target_provider_id,
            TCOResult.product_id == candidate.target_entity_id,
            TCOResult.scenario.has(PricingScenario.market_mode == scenario.market_mode),
            TCOResult.currency == (scenario.budget_preferences or {}).get("currency", ""),
        )
        .order_by(TCOResult.created_at.desc(), TCOResult.id.desc())
    ).all()
    for result in results:
        if _tco_matches_scenario(session, result, scenario):
            return result
    return None


def _tco_matches_scenario(session: Session, result: TCOResult, scenario: DecisionScenario) -> bool:
    if (
        result.completeness_status != TCOCompletenessStatus.COMPLETE.value
        or result.freshness_status != FreshnessStatus.FRESH.value
    ):
        return False
    pricing_profile = result.scenario.workload_profile
    usage_keys = {
        "storage_gb_month": "storage_gb_month",
        "requests_per_month": "requests_per_month",
        "outbound_gb": "outbound_gb",
        "monthly_hours": "compute_instance_hours",
        "vcpu": "vcpu",
        "memory_gb": "memory_gb",
    }
    for decision_key, pricing_key in usage_keys.items():
        required = scenario.workload_profile.get(decision_key)
        if required is not None and str(pricing_profile.get(pricing_key)) != str(required):
            return False
    if not tco_result_currently_complete(session, result):
        return False
    if "scoped_ecs_config" in pricing_profile:
        # The scoped validator has already reconstructed every price, policy and exclusion.
        context = pricing_profile["scoped_ecs_config"]["context"]
        return bool(
            context["market_mode"] == scenario.market_mode
            and (not scenario.country_code or context["country_code"] == scenario.country_code)
            and (not scenario.preferred_regions or context["region"] in scenario.preferred_regions)
        )
    line_items = session.scalars(
        select(CostLineItem).where(
            CostLineItem.run_id == result.run_id,
            CostLineItem.provider_id == result.provider_id,
            CostLineItem.product_id == result.product_id,
        )
    ).all()
    if not line_items or any(
        item.amount is None or item.price_snapshot is None for item in line_items
    ):
        return False
    for item in line_items:
        snapshot = item.price_snapshot
        if snapshot is None:
            return False
        if price_snapshot_freshness(snapshot) != FreshnessStatus.FRESH.value:
            return False
        region = snapshot.price_sku.region
        if scenario.country_code and region.country_code != scenario.country_code:
            return False
        if scenario.preferred_regions and region.code not in scenario.preferred_regions:
            return False
    return True


def _comparison_counts(session: Session, candidate: MappingCandidate) -> Counter[str]:
    rows = session.execute(
        select(MappingFieldComparison.comparison_status).where(
            MappingFieldComparison.mapping_candidate_id == candidate.id
        )
    ).all()
    return Counter(row[0] for row in rows)


def _target_market_block(
    session: Session,
    scenario: DecisionScenario,
    candidate: MappingCandidate,
) -> str | None:
    if candidate.rule_set.market_mode == "cross_market":
        return "cross_market_mapping_in_normal_decision"
    product = _product_for_candidate(session, candidate)
    if product is None:
        return "candidate_target_product_scope_unresolved"
    if product.provider_id != candidate.target_provider_id:
        return "candidate_target_provider_mismatch"
    if product.market_mode != scenario.market_mode:
        return (
            f"candidate target product market_mode={product.market_mode} does not match "
            f"scenario market_mode={scenario.market_mode}"
        )
    source_product = None
    if candidate.source_entity_type == "product":
        source_product = session.get(Product, candidate.source_entity_id)
    elif candidate.source_entity_type == "sku":
        source_sku = session.get(SKU, candidate.source_entity_id)
        source_product = source_sku.product if source_sku else None
    if source_product is None:
        return "candidate_source_product_scope_unresolved"
    if source_product.provider_id != candidate.source_provider_id:
        return "candidate_source_provider_mismatch"
    if source_product.market_mode != scenario.market_mode:
        return "candidate_source_market_mismatch"
    return None


def _status_from_candidate(
    *,
    candidate: MappingCandidate,
    package: EvidencePackage | None,
    tco: TCOResult | None,
    hard_blocks: list[str],
    scenario: DecisionScenario,
    scoped_model_approval: bool = False,
    requirements_need_review: bool = False,
) -> str:
    if hard_blocks:
        return DecisionStatus.BLOCKED.value
    if candidate.candidate_status in {
        MappingCandidateStatus.NOT_COMPARABLE.value,
        MappingCandidateStatus.REJECTED.value,
        MappingCandidateStatus.SUPERSEDED.value,
        MappingCandidateStatus.INSUFFICIENT_EVIDENCE.value,
    }:
        return DecisionStatus.INVALID_MAPPING.value
    if package is None or package.evidence_completeness is None:
        return DecisionStatus.INSUFFICIENT_EVIDENCE.value
    if scenario.workload_profile.get("cost_required", True) and (
        tco is None
        or tco.completeness_status != TCOCompletenessStatus.COMPLETE.value
        or tco.freshness_status != FreshnessStatus.FRESH.value
    ):
        return DecisionStatus.INCOMPLETE_COST.value
    if requirements_need_review or (
        candidate.review_status != ReviewStatus.HUMAN_REVIEWED.value and not scoped_model_approval
    ):
        return DecisionStatus.REQUIRES_REVIEW.value
    if not package.customer_eligible:
        return DecisionStatus.CONDITIONALLY_ELIGIBLE.value
    return DecisionStatus.ELIGIBLE.value


def _confidence(
    candidate: MappingCandidate,
    package: EvidencePackage | None,
    tco: TCOResult | None,
    comparison_counts: Counter[str],
    *,
    scoped_model_approval: bool = False,
) -> tuple[Decimal, str]:
    components: list[Decimal] = []
    components.append(_decimal(candidate.confidence, Decimal("0.5000")))
    components.append(_decimal(package.evidence_completeness if package else None))
    components.append(
        ONE
        if candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value or scoped_model_approval
        else Decimal("0.4000")
    )
    if tco is None:
        components.append(Decimal("0.3000"))
    elif (
        tco.completeness_status == TCOCompletenessStatus.COMPLETE.value
        and tco.freshness_status == FreshnessStatus.FRESH.value
    ):
        components.append(ONE)
    else:
        components.append(Decimal("0.5000"))
    total_comparisons = sum(comparison_counts.values())
    if total_comparisons:
        bad = comparison_counts.get("not_comparable", 0) + comparison_counts.get(
            "insufficient_evidence", 0
        )
        components.append(ONE - (Decimal(bad) / Decimal(total_comparisons)))
    score = (sum(components, ZERO) / Decimal(len(components))).quantize(Q)
    if score >= Decimal("0.8500"):
        return score, ConfidenceLevel.HIGH.value
    if score >= Decimal("0.6500"):
        return score, ConfidenceLevel.MEDIUM.value
    if score >= Decimal("0.4000"):
        return score, ConfidenceLevel.LOW.value
    return score, ConfidenceLevel.INSUFFICIENT.value


def _dimension_inputs(
    *,
    candidate: MappingCandidate,
    package: EvidencePackage | None,
    tco: TCOResult | None,
    comparison_counts: Counter[str],
    scoped_model_approval: bool = False,
) -> dict[str, tuple[Decimal | None, str, str]]:
    match_score = (
        _decimal(candidate.normalized_score)
        if candidate.normalized_score is not None and candidate.mapping_level == "sku"
        else None
    )
    package_score = (
        _decimal(package.evidence_completeness)
        if package and package.evidence_completeness is not None
        else None
    )
    # A generic comparison ratio proves neither region, SLA nor migration fitness.
    comparison_score = None
    review_score = (
        ONE
        if candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value or scoped_model_approval
        else Decimal("0.4000")
    )
    cost_score: Decimal | None = None
    cost_status = DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value
    cost_text = "No complete TCO is available; the cost dimension is excluded, not scored as zero."
    if (
        tco is not None
        and tco.completeness_status == TCOCompletenessStatus.COMPLETE.value
        and tco.freshness_status == FreshnessStatus.FRESH.value
    ):
        cost_text = "Complete scoped TCO is available, but no evidenced budget or comparable alternative establishes a cost-fit score."
    return {
        ScoringDimension.TECHNICAL_FIT.value: (
            match_score,
            DimensionScoreStatus.SCORED.value
            if match_score is not None
            else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Technical fit uses the Week 7 normalized mapping score as an input only.",
        ),
        ScoringDimension.AVAILABILITY_FIT.value: (
            comparison_score,
            DimensionScoreStatus.SCORED.value
            if comparison_score is not None
            else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Availability fit is constrained by comparable mapped fields when available.",
        ),
        ScoringDimension.REGIONAL_FIT.value: (
            comparison_score,
            DimensionScoreStatus.SCORED.value
            if comparison_score is not None
            else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Regional fit is based on mapped region/scope comparability, not a global assumption.",
        ),
        ScoringDimension.COMPLIANCE_FIT.value: (
            None,
            DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "No complete compliance product dataset is present; this dimension is not scored.",
        ),
        ScoringDimension.RELIABILITY_FIT.value: (
            comparison_score,
            DimensionScoreStatus.SCORED.value
            if comparison_score is not None
            else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Reliability fit uses comparable SLA or durability field evidence when present.",
        ),
        ScoringDimension.OPERABILITY_FIT.value: (
            None,
            DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Operational capability facts are insufficient for a numeric fit score.",
        ),
        ScoringDimension.MIGRATION_FIT.value: (
            None,
            DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Category or SKU similarity does not establish migration compatibility.",
        ),
        ScoringDimension.COST_FIT.value: (cost_score, cost_status, cost_text),
        ScoringDimension.EVIDENCE_QUALITY.value: (
            package_score,
            DimensionScoreStatus.SCORED.value
            if package
            else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Evidence quality uses Evidence Package completeness.",
        ),
        ScoringDimension.DATA_FRESHNESS.value: (
            ONE
            if package and package.freshness_status == FreshnessStatus.FRESH.value
            else Decimal("0.5000")
            if package
            else None,
            DimensionScoreStatus.SCORED.value
            if package
            else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Freshness reflects Evidence Package freshness status.",
        ),
        ScoringDimension.REVIEW_READINESS.value: (
            review_score,
            DimensionScoreStatus.REQUIRES_REVIEW.value
            if candidate.review_status != ReviewStatus.HUMAN_REVIEWED.value
            and not scoped_model_approval
            else DimensionScoreStatus.SCORED.value,
            "Verified model approval is limited to its recorded scope; it grants no customer-output authority.",
        ),
    }


def _business_fit(
    weights: dict[str, Decimal], dimensions: dict[str, tuple[Decimal | None, str, str]]
) -> Decimal | None:
    weighted = ZERO
    denominator = ZERO
    for dimension, (score, status, _) in dimensions.items():
        if score is None or status in {
            DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            DimensionScoreStatus.EXCLUDED.value,
        }:
            continue
        weight = weights.get(dimension, ZERO)
        weighted += score * weight
        denominator += weight
    if denominator == ZERO:
        return None
    return (weighted / denominator).quantize(Q)


def _completeness(dimensions: dict[str, tuple[Decimal | None, str, str]]) -> Decimal:
    if not dimensions:
        return ZERO
    present = sum(1 for score, _, _ in dimensions.values() if score is not None)
    return (Decimal(present) / Decimal(len(dimensions))).quantize(Q)


def _dependency_fingerprint(
    session: Session,
    scenario: DecisionScenario,
    policy: ScoringPolicy,
    candidates: list[MappingCandidate],
) -> str:
    def entity_category(entity_type: str, entity_id: int) -> str | None:
        if entity_type != "product":
            return None
        product = session.get(Product, entity_id)
        return product.category.code if product is not None else None

    candidate_ids = [candidate.id for candidate in candidates]
    if not candidate_ids:
        return _json_hash({"engine": ENGINE_VERSION, "candidates": []})
    comparisons = session.execute(
        select(
            MappingFieldComparison.mapping_candidate_id,
            MappingFieldComparison.id,
            MappingFieldComparison.source_value_id,
            MappingFieldComparison.target_value_id,
            MappingFieldComparison.comparison_status,
            MappingFieldComparison.blocking_reason,
        )
        .where(MappingFieldComparison.mapping_candidate_id.in_(candidate_ids))
        .order_by(MappingFieldComparison.mapping_candidate_id, MappingFieldComparison.id)
    ).all()
    linked_sources = session.execute(
        select(
            MappingCandidateEvidence.mapping_candidate_id,
            Evidence.id,
            Evidence.locator,
            Evidence.excerpt,
            SourceDocument.content_hash,
        )
        .join(Evidence, MappingCandidateEvidence.evidence_id == Evidence.id)
        .join(SourceDocument, Evidence.source_document_id == SourceDocument.id)
        .where(MappingCandidateEvidence.mapping_candidate_id.in_(candidate_ids))
        .order_by(MappingCandidateEvidence.mapping_candidate_id, Evidence.id)
    ).all()
    packages = session.scalars(
        select(EvidencePackage).where(EvidencePackage.mapping_candidate_id.in_(candidate_ids))
    ).all()
    package_items = (
        session.execute(
            select(
                EvidencePackageItem.package_id,
                EvidencePackageItem.id,
                EvidencePackageItem.source_value_id,
                EvidencePackageItem.target_value_id,
                EvidencePackageItem.comparison_status,
                EvidencePackageItem.scope_status,
                EvidencePackageItem.qualifier_status,
                EvidencePackageItem.blocking_reason,
            )
            .where(EvidencePackageItem.package_id.in_([package.id for package in packages]))
            .order_by(EvidencePackageItem.package_id, EvidencePackageItem.id)
        ).all()
        if packages
        else []
    )
    tco = session.scalars(select(TCOResult).order_by(TCOResult.id)).all()
    cost_items = session.execute(
        select(
            CostLineItem.id,
            CostLineItem.run_id,
            CostLineItem.product_id,
            CostLineItem.dimension,
            CostLineItem.amount,
            CostLineItem.price_snapshot_id,
            CostLineItem.missing_reason,
        ).order_by(CostLineItem.id)
    ).all()
    price_snapshots = session.execute(
        select(
            PriceSnapshot.id,
            PriceSnapshot.captured_at,
            PriceSnapshot.effective_to,
            PriceSnapshot.unit_price,
            PriceSnapshot.evidence_id,
        ).order_by(PriceSnapshot.id)
    ).all()
    normalized_values = session.execute(
        select(
            NormalizedSpecification.id,
            NormalizedSpecification.product_id,
            NormalizedSpecification.sku_id,
            NormalizedSpecification.canonical_field_id,
            NormalizedSpecification.scope_type,
            NormalizedSpecification.scope_identity,
            NormalizedSpecification.value_qualifier,
            NormalizedSpecification.canonical_value,
            NormalizedSpecification.numeric_value,
            NormalizedSpecification.text_value,
            NormalizedSpecification.boolean_value,
            NormalizedSpecification.canonical_unit,
            NormalizedSpecification.evidence_id,
            NormalizedSpecification.review_status,
            NormalizedSpecification.source_value_hash,
        ).order_by(NormalizedSpecification.id)
    ).all()
    return _json_hash(
        {
            "engine": ENGINE_VERSION,
            "implementation_state": implementation_state(),
            "freshness_day": datetime.now(UTC).date().isoformat(),
            "scenario": [
                scenario.id,
                scenario.market_mode,
                scenario.workload_profile,
                scenario.technical_requirements,
                scenario.budget_preferences,
                scenario.country_code,
                scenario.preferred_regions,
                scenario.availability_requirements,
                scenario.compliance_requirements,
                scenario.data_residency_requirements,
                scenario.operational_requirements,
                scenario.migration_requirements,
            ],
            "requirements": [
                [
                    item.id,
                    item.requirement_code,
                    item.requirement_type,
                    item.required_value,
                    item.operator,
                    item.unit,
                    item.scope,
                    item.qualifier,
                    item.priority,
                    item.is_mandatory,
                    item.missing_data_policy,
                    item.evidence_requirement,
                ]
                for item in sorted(scenario.requirements, key=lambda item: item.id)
            ],
            "mapping_approvals": [mapping_approval(session, candidate) for candidate in candidates],
            "policy": [
                policy.id,
                policy.policy_version,
                policy.dimension_weights,
                policy.hard_block_rules,
                policy.missing_data_policy,
                policy.confidence_policy,
                policy.thresholds,
                policy.effective_from,
                policy.deprecated_at,
                policy.status,
            ],
            "policy_rules": [
                [
                    rule.id,
                    rule.rule_code,
                    rule.rule_version,
                    rule.dimension,
                    rule.canonical_field_id,
                    rule.operator,
                    rule.expected_value,
                    rule.minimum_score,
                    rule.maximum_score,
                    rule.score_function,
                    rule.conditions,
                    rule.evidence_requirement,
                    rule.missing_data_policy,
                    rule.priority,
                    rule.status,
                ]
                for rule in sorted(policy.rules, key=lambda rule: rule.id)
            ],
            "candidates": [
                [
                    candidate.id,
                    candidate.candidate_status,
                    candidate.review_status,
                    candidate.blocking_reasons,
                    candidate.relationship_type,
                    candidate.normalized_score,
                    candidate.confidence,
                    candidate.rule_set.market_mode,
                    candidate.rule_set.category,
                    entity_category(candidate.source_entity_type, candidate.source_entity_id),
                    entity_category(candidate.target_entity_type, candidate.target_entity_id),
                ]
                for candidate in candidates
            ],
            "comparisons": comparisons,
            "linked_sources": linked_sources,
            "packages": [
                [
                    package.id,
                    package.mapping_candidate_id,
                    package.content_hash,
                    package.review_status,
                    package.customer_eligible,
                    package.evidence_completeness,
                    package.freshness_status,
                ]
                for package in packages
            ],
            "package_items": package_items,
            "tco": [
                [
                    row.id,
                    row.product_id,
                    row.scenario.market_mode,
                    row.total,
                    row.completeness_status,
                    row.freshness_status,
                    row.created_at,
                ]
                for row in tco
            ],
            "cost_items": cost_items,
            "price_snapshots": price_snapshots,
            "normalized_values": normalized_values,
            "current_source_state": current_source_state(session, _now()),
        }
    )


def _run_code(
    scenario: DecisionScenario,
    policy: ScoringPolicy,
    price_cutoff: datetime,
    dependency_hash: str,
) -> str:
    digest = _json_hash(
        {
            "scenario": scenario.scenario_code,
            "scenario_version": scenario.scenario_version,
            "policy": policy.policy_code,
            "policy_version": policy.policy_version,
            "price_cutoff": price_cutoff.isoformat(),
            "dependency_hash": dependency_hash,
        }
    )[:12]
    return f"{scenario.scenario_code}_{scenario.scenario_version}_{policy.policy_version}_{digest}"


def run_decision_engine(
    session: Session,
    scenario_code: str,
    *,
    dry_run: bool = False,
) -> RunSummary:
    scenario = session.scalar(
        select(DecisionScenario).where(
            DecisionScenario.scenario_code == scenario_code,
            DecisionScenario.status == "active",
        )
    )
    if scenario is None or scenario.scoring_policy_id is None:
        raise ValueError(f"active scenario with policy not found: {scenario_code}")
    policy = session.get(ScoringPolicy, scenario.scoring_policy_id)
    if policy is None:
        raise ValueError(f"scenario policy not found: {scenario_code}")
    generated_at = _now()
    price_cutoff = _latest_price_cutoff(session)
    candidates = list(session.execute(_candidate_query(scenario)).scalars())
    dependency_hash = _dependency_fingerprint(session, scenario, policy, candidates)
    run_code = _run_code(scenario, policy, price_cutoff, dependency_hash)
    existing = session.scalar(select(DecisionRun).where(DecisionRun.run_code == run_code))
    if existing is not None:
        return RunSummary(
            run_code=existing.run_code,
            scenario_code=scenario.scenario_code,
            scenario_version=scenario.scenario_version,
            status=existing.status,
            candidate_count=existing.candidate_count,
            eligible_count=existing.eligible_count,
            blocked_count=existing.blocked_count,
            review_count=existing.review_count,
            warning_count=existing.warning_count,
            created=False,
        )
    status = DecisionRunStatus.DRY_RUN.value if dry_run else DecisionRunStatus.SUCCEEDED.value
    content_hash = dependency_hash
    run = DecisionRun(
        run_code=run_code,
        scenario_id=scenario.id,
        scenario_version=scenario.scenario_version,
        policy_id=policy.id,
        policy_version=policy.policy_version,
        mapping_cutoff=generated_at,
        evidence_cutoff=generated_at,
        price_cutoff=price_cutoff,
        generated_at=generated_at,
        status=status,
        candidate_count=0,
        eligible_count=0,
        blocked_count=0,
        review_count=0,
        warning_count=0,
        content_hash=content_hash,
    )
    session.add(run)
    session.flush()

    weights = _weights(policy)
    counters: Counter[str] = Counter()
    for candidate in candidates:
        package = _latest_package(session, candidate)
        tco = _latest_tco(session, candidate, scenario)
        comparisons = _comparison_counts(session, candidate)
        approval = mapping_approval(session, candidate)
        requirement_outcomes = evaluate_scenario_requirements(session, scenario, candidate, tco)
        rule_evidence_ids = tuple(
            sorted(
                {link.evidence_id for link in candidate.evidence_links}
                | {eid for outcome in requirement_outcomes for eid in outcome.evidence_ids}
            )
        )
        policy_outcomes = [
            evaluate_policy_rule(rule, candidate, package, tco, rule_evidence_ids)
            for rule in policy.rules
            if rule.status == "active"
        ]
        hard_blocks: list[str] = []
        market_block = _target_market_block(session, scenario, candidate)
        if market_block:
            hard_blocks.append(market_block)
        hard_blocks.extend(
            outcome.reason
            for outcome in requirement_outcomes
            if outcome.hard_block and outcome.reason
        )
        hard_blocks.extend(
            outcome.reason for outcome in policy_outcomes if outcome.hard_block and outcome.reason
        )
        decision_status = _status_from_candidate(
            candidate=candidate,
            package=package,
            tco=tco,
            hard_blocks=hard_blocks,
            scenario=scenario,
            scoped_model_approval=approval is not None,
            requirements_need_review=any(
                outcome.requires_review for outcome in requirement_outcomes
            )
            or any(outcome.requires_review for outcome in policy_outcomes),
        )
        dimensions = _dimension_inputs(
            candidate=candidate,
            package=package,
            tco=tco,
            comparison_counts=comparisons,
            scoped_model_approval=approval is not None,
        )
        for dimension in {outcome.dimension for outcome in requirement_outcomes}:
            outcomes = [
                outcome for outcome in requirement_outcomes if outcome.dimension == dimension
            ]
            if dimension not in dimensions or dimension == ScoringDimension.COST_FIT.value:
                continue
            known = all(outcome.status in {"pass", "fail"} for outcome in outcomes)
            dimensions[dimension] = (
                (
                    Decimal(sum(outcome.status == "pass" for outcome in outcomes))
                    / Decimal(len(outcomes))
                ).quantize(Q)
                if known
                else None,
                DimensionScoreStatus.SCORED.value
                if known
                else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
                "Target scenario requirements evaluated from scope-matched official evidence; no cross-vendor equivalence is asserted.",
            )
        for dimension, (_, _, explanation) in list(dimensions.items()):
            if weights.get(dimension, ZERO) == ZERO:
                dimensions[dimension] = (
                    None,
                    DimensionScoreStatus.EXCLUDED.value,
                    "Outside this policy's declared scoring scope. " + explanation,
                )
        reference_fit = _business_fit(weights, dimensions)
        business_fit = (
            None
            if hard_blocks or (policy.thresholds or {}).get("business_fit_enabled") is False
            else reference_fit
        )
        confidence_score, confidence_level = _confidence(
            candidate, package, tco, comparisons, scoped_model_approval=approval is not None
        )
        completeness_score = _completeness(
            {key: value for key, value in dimensions.items() if weights.get(key, ZERO) > ZERO}
        )
        result = CandidateDecisionResult(
            decision_run_id=run.id,
            mapping_candidate_id=candidate.id,
            provider_id=candidate.target_provider_id,
            entity_type=candidate.target_entity_type,
            entity_id=candidate.target_entity_id,
            decision_status=decision_status,
            business_fit_score=business_fit,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            completeness_score=completeness_score,
            match_score=_decimal(candidate.normalized_score)
            if candidate.normalized_score is not None
            else None,
            tco_result_id=tco.id if tco else None,
            hard_block_count=len(hard_blocks),
            warning_count=1
            if decision_status
            in {DecisionStatus.REQUIRES_REVIEW.value, DecisionStatus.INCOMPLETE_COST.value}
            else 0,
            rank=None,
            explanation=(
                "Machine-generated internal decision candidate. Hard blockers, review "
                "status, confidence, completeness, and TCO completeness must be reviewed "
                "before any customer-facing use."
            ),
            assumptions=[
                "Directory pricing is not a customer transaction price.",
                "Missing cost inputs are excluded and lower confidence; they are not treated as zero.",
                "Pending-review evidence keeps the result internal-only.",
            ],
            key_strength_conditions=[
                {
                    "type": "relative_strength_condition",
                    "condition": "Evidence-backed mapping similarity is available.",
                    "evidence_package_id": package.id if package else None,
                    "confidence": str(confidence_score),
                }
            ]
            if package
            and candidate.normalized_score is not None
            and candidate.mapping_level == "sku"
            else [],
            key_risks=[
                {"type": "relative_risk", "reason": reason, "severity": "critical"}
                for reason in hard_blocks
            ],
            missing_information=[
                {
                    "type": "missing_information",
                    "dimension": ScoringDimension.COST_FIT.value,
                    "reason": "complete TCO not available for this mapped candidate",
                }
            ]
            if tco is None or tco.completeness_status != TCOCompletenessStatus.COMPLETE.value
            else [],
            valid_from=generated_at,
            review_status=DecisionReviewStatus.MACHINE_GENERATED.value,
            output_level=DecisionOutputLevel.INTERNAL_ONLY.value,
            customer_eligible=False,
        )
        session.add(result)
        session.flush()
        result.missing_information = list(result.missing_information or []) + [
            {"type": "missing_information", "requirement": outcome.code, "reason": outcome.reason}
            for outcome in requirement_outcomes
            if outcome.status == "missing_data"
        ]
        result.missing_information += [
            {
                "type": "missing_information",
                "scoring_rule_id": outcome.rule_id,
                "reason": outcome.reason,
            }
            for outcome in policy_outcomes
            if outcome.status == "missing_data"
        ]
        for policy_outcome in policy_outcomes:
            session.add(
                RuleEvaluation(
                    candidate_result_id=result.id,
                    scoring_rule_id=policy_outcome.rule_id,
                    result_status=policy_outcome.status,
                    score=policy_outcome.score,
                    hard_block=policy_outcome.hard_block,
                    blocking_reason=policy_outcome.reason,
                    observed_value=policy_outcome.observed,
                    expected_value=policy_outcome.expected,
                    evidence_reference_ids=list(policy_outcome.evidence_ids),
                )
            )
        for outcome in requirement_outcomes:
            session.add(
                RuleEvaluation(
                    candidate_result_id=result.id,
                    requirement_id=outcome.requirement_id,
                    result_status=outcome.status,
                    score=ONE
                    if outcome.status == "pass"
                    else ZERO
                    if outcome.status == "fail"
                    else None,
                    hard_block=outcome.hard_block,
                    blocking_reason=outcome.reason,
                    observed_value=json.loads(json.dumps(outcome.observed, default=str)),
                    expected_value=outcome.expected,
                    evidence_reference_ids=list(outcome.evidence_ids),
                )
            )
        for dimension, (score, dimension_status, explanation) in dimensions.items():
            weight = weights.get(dimension, ZERO)
            session.add(
                DimensionScore(
                    candidate_result_id=result.id,
                    dimension=dimension,
                    raw_score=score,
                    normalized_score=score,
                    weight=weight,
                    weighted_score=(score * weight).quantize(Q) if score is not None else None,
                    confidence=confidence_score,
                    completeness=ONE if score is not None else ZERO,
                    status=dimension_status,
                    explanation=explanation,
                    evidence_package_id=package.id if package else None,
                )
            )
        for reason in [market_block] if market_block else []:
            session.add(
                RuleEvaluation(
                    candidate_result_id=result.id,
                    result_status=RuleEvaluationStatus.FAIL.value,
                    score=None,
                    hard_block=True,
                    blocking_reason=reason,
                    observed_value={"candidate_id": candidate.id},
                    expected_value={"scenario_market_mode": scenario.market_mode},
                    evidence_reference_ids=[],
                )
            )
        counters[decision_status] += 1

    _assign_ranks(session, run)
    run.candidate_count = len(candidates)
    run.eligible_count = (
        counters[DecisionStatus.ELIGIBLE.value]
        + counters[DecisionStatus.CONDITIONALLY_ELIGIBLE.value]
    )
    run.blocked_count = (
        counters[DecisionStatus.BLOCKED.value] + counters[DecisionStatus.INVALID_MAPPING.value]
    )
    run.review_count = counters[DecisionStatus.REQUIRES_REVIEW.value]
    run.warning_count = counters[DecisionStatus.INCOMPLETE_COST.value] + run.review_count
    _upsert_sensitivity(session, run)
    summary = RunSummary(
        run_code=run.run_code,
        scenario_code=scenario.scenario_code,
        scenario_version=scenario.scenario_version,
        status=run.status,
        candidate_count=run.candidate_count,
        eligible_count=run.eligible_count,
        blocked_count=run.blocked_count,
        review_count=run.review_count,
        warning_count=run.warning_count,
        created=True,
    )
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return summary


def _assign_ranks(session: Session, run: DecisionRun) -> None:
    eligible_statuses = {DecisionStatus.ELIGIBLE.value, DecisionStatus.CONDITIONALLY_ELIGIBLE.value}
    results = list(
        session.execute(
            select(CandidateDecisionResult)
            .where(CandidateDecisionResult.decision_run_id == run.id)
            .order_by(
                CandidateDecisionResult.business_fit_score.desc().nullslast(),
                CandidateDecisionResult.confidence_score.desc().nullslast(),
                CandidateDecisionResult.completeness_score.desc().nullslast(),
                CandidateDecisionResult.id,
            )
        ).scalars()
    )
    rank = 0
    previous_score: Decimal | None = None
    minimum_fit = _decimal(
        (run.policy.thresholds or {}).get("minimum_business_fit"), Decimal("0.6500")
    )
    minimum_confidence = _decimal(
        (run.policy.confidence_policy or {}).get("minimum_for_ranking"), Decimal("0.6500")
    )
    for result in results:
        if (
            (run.policy.thresholds or {}).get("ranking_enabled") is False
            or result.decision_status not in eligible_statuses
            or result.hard_block_count > 0
            or result.business_fit_score is None
            or result.confidence_score is None
            or result.confidence_score < minimum_confidence
            or result.business_fit_score < minimum_fit
        ):
            result.rank = None
            continue
        if previous_score is None or result.business_fit_score != previous_score:
            rank += 1
            previous_score = result.business_fit_score
        result.rank = rank


def _upsert_sensitivity(session: Session, run: DecisionRun) -> None:
    existing = session.scalar(
        select(DecisionSensitivityResult).where(
            DecisionSensitivityResult.decision_run_id == run.id,
            DecisionSensitivityResult.analysis_code == "weight_plus_minus_10pct_measured_v1",
        )
    )
    if existing is not None:
        return
    session.flush()
    results = list(
        session.scalars(
            select(CandidateDecisionResult).where(CandidateDecisionResult.decision_run_id == run.id)
        )
    )
    payload = analyze_weight_sensitivity(
        candidate_dimensions={
            result.id: {
                score.dimension: (score.normalized_score, score.status)
                for score in result.dimension_scores
            }
            for result in results
        },
        weights=_weights(run.policy),
        eligible_candidate_ids=[result.id for result in results if result.rank is not None],
        baseline_ranks={result.id: result.rank for result in results},
    )
    session.add(
        DecisionSensitivityResult(
            decision_run_id=run.id,
            analysis_code="weight_plus_minus_10pct_measured_v1",
            **payload,
        )
    )


def result_rows(session: Session, run_code: str) -> list[dict[str, Any]]:
    run = session.scalar(select(DecisionRun).where(DecisionRun.run_code == run_code))
    if run is None:
        raise ValueError(f"DecisionRun not found: {run_code}")
    rows: list[dict[str, Any]] = []
    for result in session.execute(
        select(CandidateDecisionResult).where(CandidateDecisionResult.decision_run_id == run.id)
    ).scalars():
        provider = session.get(Provider, result.provider_id)
        rows.append(
            {
                "decision_result_id": result.id,
                "run_code": run.run_code,
                "scenario_code": run.scenario.scenario_code,
                "scenario_version": run.scenario_version,
                "provider": provider.code if provider else str(result.provider_id),
                "entity": f"{result.entity_type}:{result.entity_id}",
                "mapping_candidate_id": result.mapping_candidate_id,
                "decision_status": result.decision_status,
                "business_fit_score": str(result.business_fit_score)
                if result.business_fit_score is not None
                else "",
                "match_score": str(result.match_score) if result.match_score is not None else "",
                "confidence_score": str(result.confidence_score)
                if result.confidence_score is not None
                else "",
                "completeness_score": str(result.completeness_score)
                if result.completeness_score is not None
                else "",
                "rank": result.rank or "",
                "hard_blocks": result.hard_block_count,
                "dimension_scores": {
                    score.dimension: str(score.normalized_score)
                    if score.normalized_score is not None
                    else None
                    for score in result.dimension_scores
                },
                "key_strength_conditions": result.key_strength_conditions or [],
                "key_risks": result.key_risks or [],
                "missing_information": result.missing_information or [],
                "assumptions": result.assumptions or [],
                "tco_result": result.tco_result_id or "",
                "evidence_packages": [
                    score.evidence_package_id
                    for score in result.dimension_scores
                    if score.evidence_package_id is not None
                ],
                "sensitivity_status": "",
                "review_result": "",
                "reviewer": "",
                "reviewer_notes": "",
            }
        )
    return rows


def write_review_sample(session: Session, run_code: str, path: Path = REVIEW_SAMPLE_PATH) -> None:
    rows = result_rows(session, run_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "decision_result_id",
        "scenario_code",
        "scenario_version",
        "provider",
        "entity",
        "mapping_candidate_id",
        "decision_status",
        "business_fit_score",
        "match_score",
        "confidence_score",
        "completeness_score",
        "rank",
        "hard_blocks",
        "dimension_scores",
        "key_strength_conditions",
        "key_risks",
        "missing_information",
        "assumptions",
        "tco_result",
        "evidence_packages",
        "sensitivity_status",
        "review_result",
        "reviewer",
        "reviewer_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows[:120]:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
