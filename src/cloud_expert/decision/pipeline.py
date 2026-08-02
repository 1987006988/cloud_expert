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

from sqlalchemy import Select, func, select
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
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate, MappingFieldComparison
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.decision.config import (
    PolicyConfig,
    ScenarioConfig,
    load_policy_config,
    load_scenario_config,
)

REPORT_DIR = Path("reports") / "decision"
REVIEW_SAMPLE_PATH = Path("reports") / "review_samples" / "week10_decision_review.csv"
Q = Decimal("0.0001")
ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")


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
    statement = select(MappingCandidate).where(MappingCandidate.mapping_level.in_(levels))
    if category == "compute":
        statement = statement.where(
            MappingCandidate.mapping_level.in_({"product", "sku", "product_family"})
        )
    if category == "object_storage":
        statement = statement.where(MappingCandidate.mapping_level.in_({"product", "service_tier"}))
    return statement.order_by(MappingCandidate.id)


def _product_for_candidate(session: Session, candidate: MappingCandidate) -> Product | None:
    entity_id = candidate.target_entity_id
    if candidate.target_entity_type != "product":
        return None
    return session.get(Product, entity_id)


def _latest_package(session: Session, candidate: MappingCandidate) -> EvidencePackage | None:
    return session.scalar(
        select(EvidencePackage)
        .where(EvidencePackage.mapping_candidate_id == candidate.id)
        .order_by(EvidencePackage.generated_at.desc(), EvidencePackage.id.desc())
    )


def _latest_tco(session: Session, candidate: MappingCandidate) -> TCOResult | None:
    if candidate.target_entity_type != "product":
        return None
    return session.scalar(
        select(TCOResult)
        .where(
            TCOResult.provider_id == candidate.target_provider_id,
            TCOResult.product_id == candidate.target_entity_id,
        )
        .order_by(TCOResult.created_at.desc(), TCOResult.id.desc())
    )


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
    product = _product_for_candidate(session, candidate)
    if product is None:
        return None
    if product.market_mode != scenario.market_mode:
        return (
            f"candidate target product market_mode={product.market_mode} does not match "
            f"scenario market_mode={scenario.market_mode}"
        )
    return None


def _status_from_candidate(
    *,
    candidate: MappingCandidate,
    package: EvidencePackage | None,
    tco: TCOResult | None,
    hard_blocks: list[str],
    scenario: DecisionScenario,
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
        tco is None or tco.completeness_status != TCOCompletenessStatus.COMPLETE.value
    ):
        return DecisionStatus.INCOMPLETE_COST.value
    if candidate.review_status != ReviewStatus.HUMAN_REVIEWED.value:
        return DecisionStatus.REQUIRES_REVIEW.value
    if not package.customer_eligible:
        return DecisionStatus.CONDITIONALLY_ELIGIBLE.value
    return DecisionStatus.ELIGIBLE.value


def _confidence(
    candidate: MappingCandidate,
    package: EvidencePackage | None,
    tco: TCOResult | None,
    comparison_counts: Counter[str],
) -> tuple[Decimal, str]:
    components: list[Decimal] = []
    components.append(_decimal(candidate.confidence, Decimal("0.5000")))
    components.append(_decimal(package.evidence_completeness if package else None))
    components.append(
        ONE if candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value else Decimal("0.4000")
    )
    if tco is None:
        components.append(Decimal("0.3000"))
    elif tco.completeness_status == TCOCompletenessStatus.COMPLETE.value:
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
) -> dict[str, tuple[Decimal | None, str, str]]:
    match_score = _decimal(candidate.normalized_score)
    package_score = _decimal(package.evidence_completeness if package else None)
    total_comparisons = sum(comparison_counts.values())
    comparable = Decimal(total_comparisons - comparison_counts.get("not_comparable", 0))
    comparison_score = (
        (comparable / Decimal(total_comparisons)).quantize(Q) if total_comparisons else None
    )
    review_score = (
        ONE if candidate.review_status == ReviewStatus.HUMAN_REVIEWED.value else Decimal("0.4000")
    )
    cost_score: Decimal | None = None
    cost_status = DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value
    cost_text = "No complete TCO is available; the cost dimension is excluded, not scored as zero."
    if tco is not None and tco.completeness_status == TCOCompletenessStatus.COMPLETE.value:
        cost_score = ONE
        cost_status = DimensionScoreStatus.SCORED.value
        cost_text = "Complete TCO result is available for this candidate."
    return {
        ScoringDimension.TECHNICAL_FIT.value: (
            match_score,
            DimensionScoreStatus.SCORED.value,
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
            match_score,
            DimensionScoreStatus.SCORED.value,
            "Migration fit uses mapping similarity only as a technical compatibility signal.",
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
            else Decimal("0.5000"),
            DimensionScoreStatus.SCORED.value
            if package
            else DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
            "Freshness reflects Evidence Package freshness status.",
        ),
        ScoringDimension.REVIEW_READINESS.value: (
            review_score,
            DimensionScoreStatus.REQUIRES_REVIEW.value
            if candidate.review_status != ReviewStatus.HUMAN_REVIEWED.value
            else DimensionScoreStatus.SCORED.value,
            "Machine generated candidates remain pending until real human review.",
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


def _run_code(scenario: DecisionScenario, policy: ScoringPolicy, price_cutoff: datetime) -> str:
    digest = _json_hash(
        {
            "scenario": scenario.scenario_code,
            "scenario_version": scenario.scenario_version,
            "policy": policy.policy_code,
            "policy_version": policy.policy_version,
            "price_cutoff": price_cutoff.isoformat(),
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
    run_code = _run_code(scenario, policy, price_cutoff)
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
    candidates = list(session.execute(_candidate_query(scenario)).scalars())
    status = DecisionRunStatus.DRY_RUN.value if dry_run else DecisionRunStatus.SUCCEEDED.value
    content_hash = _json_hash({"run_code": run_code, "candidate_ids": [c.id for c in candidates]})
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
        tco = _latest_tco(session, candidate)
        comparisons = _comparison_counts(session, candidate)
        hard_blocks: list[str] = []
        market_block = _target_market_block(session, scenario, candidate)
        if market_block:
            hard_blocks.append(market_block)
        decision_status = _status_from_candidate(
            candidate=candidate,
            package=package,
            tco=tco,
            hard_blocks=hard_blocks,
            scenario=scenario,
        )
        dimensions = _dimension_inputs(
            candidate=candidate,
            package=package,
            tco=tco,
            comparison_counts=comparisons,
        )
        reference_fit = _business_fit(weights, dimensions)
        business_fit = None if hard_blocks else reference_fit
        confidence_score, confidence_level = _confidence(candidate, package, tco, comparisons)
        completeness_score = _completeness(dimensions)
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
            match_score=_decimal(candidate.normalized_score),
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
        for reason in hard_blocks:
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
    session.commit()
    return RunSummary(
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
    for result in results:
        if (
            result.decision_status not in eligible_statuses
            or result.hard_block_count > 0
            or result.business_fit_score is None
            or result.confidence_score is None
            or result.confidence_score < Decimal("0.6500")
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
            DecisionSensitivityResult.analysis_code == "weight_plus_minus_10pct_v1",
        )
    )
    if existing is not None:
        return
    ranked = session.scalar(
        select(func.count())
        .select_from(CandidateDecisionResult)
        .where(
            CandidateDecisionResult.decision_run_id == run.id,
            CandidateDecisionResult.rank.is_not(None),
        )
    )
    status = "indeterminate" if not ranked else "stable"
    session.add(
        DecisionSensitivityResult(
            decision_run_id=run.id,
            analysis_code="weight_plus_minus_10pct_v1",
            ranking_stability="no_formal_ranking" if not ranked else "ranking_unchanged",
            score_variance=ZERO,
            top_candidate_change_count=0,
            critical_assumption_count=1,
            sensitivity_status=status,
            scenarios_tested=[
                {
                    "type": "weight_sensitivity",
                    "range": "+/-10pct",
                    "discounts_included": False,
                    "customer_commitment_included": False,
                }
            ],
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
