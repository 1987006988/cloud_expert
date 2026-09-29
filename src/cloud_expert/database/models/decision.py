from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import (
    ConfidenceLevel,
    DecisionOutputLevel,
    DecisionReviewStatus,
    DecisionRunStatus,
    DecisionScenarioStatus,
    DecisionScenarioType,
    DecisionStatus,
    DimensionScoreStatus,
    MarketMode,
    MissingDataPolicy,
    RuleEvaluationStatus,
    ScenarioRequirementOperator,
    ScenarioRequirementPriority,
    ScenarioRequirementType,
    ScoreFunction,
    ScoringDimension,
    ScoringPolicyStatus,
    SensitivityStatus,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.canonical import CanonicalFieldDefinition
    from cloud_expert.database.models.evidence_package import EvidencePackage
    from cloud_expert.database.models.mapping import MappingCandidate
    from cloud_expert.database.models.provider import Provider
    from cloud_expert.database.models.tco import TCOResult


class DecisionScenario(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("scenario_code", "scenario_version", name="uq_decision_scenario_version"),
        CheckConstraint(
            f"scenario_type IN ({sql_in_values(DecisionScenarioType.values())})",
            name="decision_scenario_type",
        ),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.fact_values())})",
            name="decision_scenario_market_mode",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(DecisionScenarioStatus.values())})",
            name="decision_scenario_status",
        ),
    )

    scenario_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    scenario_version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    market_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128))
    country_code: Mapped[str | None] = mapped_column(String(8))
    preferred_regions: Mapped[list[str] | None] = mapped_column(JSON)
    workload_profile: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    technical_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    availability_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    compliance_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    data_residency_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    operational_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    migration_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    budget_preferences: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    scoring_policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("scoring_policy.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scoring_policy: Mapped[ScoringPolicy | None] = relationship(back_populates="scenarios")
    requirements: Mapped[list[ScenarioRequirement]] = relationship(back_populates="scenario")
    runs: Mapped[list[DecisionRun]] = relationship(back_populates="scenario")


class ScenarioRequirement(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "scenario_id",
            "requirement_code",
            name="uq_scenario_requirement_code",
        ),
        CheckConstraint(
            f"requirement_type IN ({sql_in_values(ScenarioRequirementType.values())})",
            name="scenario_requirement_type",
        ),
        CheckConstraint(
            f"operator IN ({sql_in_values(ScenarioRequirementOperator.values())})",
            name="scenario_requirement_operator",
        ),
        CheckConstraint(
            f"priority IN ({sql_in_values(ScenarioRequirementPriority.values())})",
            name="scenario_requirement_priority",
        ),
        CheckConstraint(
            f"missing_data_policy IN ({sql_in_values(MissingDataPolicy.values())})",
            name="scenario_requirement_missing_policy",
        ),
    )

    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("decision_scenario.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requirement_code: Mapped[str] = mapped_column(String(160), nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_field_definition.id", ondelete="RESTRICT"),
        index=True,
    )
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    required_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(64))
    qualifier: Mapped[str | None] = mapped_column(String(64))
    scope: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(64), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_data_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_requirement: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scenario: Mapped[DecisionScenario] = relationship(back_populates="requirements")
    canonical_field: Mapped[CanonicalFieldDefinition | None] = relationship()


class ScoringPolicy(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("policy_code", "policy_version", name="uq_scoring_policy_version"),
        CheckConstraint(
            f"scenario_type IN ({sql_in_values(DecisionScenarioType.values())})",
            name="scoring_policy_scenario_type",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(ScoringPolicyStatus.values())})",
            name="scoring_policy_status",
        ),
    )

    policy_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dimension_weights: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    hard_block_rules: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    missing_data_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scenarios: Mapped[list[DecisionScenario]] = relationship(back_populates="scoring_policy")
    rules: Mapped[list[ScoringRule]] = relationship(back_populates="policy")


class ScoringRule(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("policy_id", "rule_code", "rule_version", name="uq_scoring_rule_version"),
        CheckConstraint(
            f"dimension IN ({sql_in_values(ScoringDimension.values())})",
            name="scoring_rule_dimension",
        ),
        CheckConstraint(
            f"operator IN ({sql_in_values(ScenarioRequirementOperator.values())})",
            name="scoring_rule_operator",
        ),
        CheckConstraint(
            f"score_function IN ({sql_in_values(ScoreFunction.values())})",
            name="scoring_rule_score_function",
        ),
        CheckConstraint(
            f"missing_data_policy IN ({sql_in_values(MissingDataPolicy.values())})",
            name="scoring_rule_missing_policy",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(ScoringPolicyStatus.values())})",
            name="scoring_rule_status",
        ),
        CheckConstraint(
            "minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 1)",
            name="scoring_rule_min_score",
        ),
        CheckConstraint(
            "maximum_score IS NULL OR (maximum_score >= 0 AND maximum_score <= 1)",
            name="scoring_rule_max_score",
        ),
    )

    policy_id: Mapped[int] = mapped_column(
        ForeignKey("scoring_policy.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_field_definition.id", ondelete="RESTRICT"),
        index=True,
    )
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    minimum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    maximum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    score_function: Mapped[str] = mapped_column(String(64), nullable=False)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_requirement: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    missing_data_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    policy: Mapped[ScoringPolicy] = relationship(back_populates="rules")
    canonical_field: Mapped[CanonicalFieldDefinition | None] = relationship()


class DecisionRun(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("run_code", name="uq_decision_run_code"),
        UniqueConstraint(
            "scenario_id",
            "scenario_version",
            "policy_id",
            "policy_version",
            "mapping_cutoff",
            "evidence_cutoff",
            "price_cutoff",
            "status",
            name="uq_decision_run_natural_key",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(DecisionRunStatus.values())})",
            name="decision_run_status",
        ),
        CheckConstraint("candidate_count >= 0", name="decision_run_candidate_count"),
        CheckConstraint("eligible_count >= 0", name="decision_run_eligible_count"),
        CheckConstraint("blocked_count >= 0", name="decision_run_blocked_count"),
        CheckConstraint("review_count >= 0", name="decision_run_review_count"),
        CheckConstraint("warning_count >= 0", name="decision_run_warning_count"),
    )

    run_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("decision_scenario.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scenario_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("scoring_policy.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_count: Mapped[int] = mapped_column(nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scenario: Mapped[DecisionScenario] = relationship(back_populates="runs")
    policy: Mapped[ScoringPolicy] = relationship()
    results: Mapped[list[CandidateDecisionResult]] = relationship(back_populates="decision_run")


class CandidateDecisionResult(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "decision_run_id",
            "mapping_candidate_id",
            name="uq_candidate_decision_result_run_candidate",
        ),
        CheckConstraint(
            f"decision_status IN ({sql_in_values(DecisionStatus.values())})",
            name="candidate_decision_status",
        ),
        CheckConstraint(
            f"confidence_level IN ({sql_in_values(ConfidenceLevel.values())})",
            name="candidate_decision_confidence_level",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(DecisionReviewStatus.values())})",
            name="candidate_decision_review_status",
        ),
        CheckConstraint(
            f"output_level IN ({sql_in_values(DecisionOutputLevel.values())})",
            name="candidate_decision_output_level",
        ),
        CheckConstraint(
            "business_fit_score IS NULL OR (business_fit_score >= 0 AND business_fit_score <= 1)",
            name="candidate_decision_business_fit_score",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="candidate_decision_confidence_score",
        ),
        CheckConstraint(
            "completeness_score IS NULL OR (completeness_score >= 0 AND completeness_score <= 1)",
            name="candidate_decision_completeness_score",
        ),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="candidate_decision_match_score",
        ),
        CheckConstraint("hard_block_count >= 0", name="candidate_decision_hard_blocks"),
        CheckConstraint("warning_count >= 0", name="candidate_decision_warning_count"),
    )

    decision_run_id: Mapped[int] = mapped_column(
        ForeignKey("decision_run.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mapping_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("mapping_candidate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(nullable=False, index=True)
    decision_status: Mapped[str] = mapped_column(String(64), nullable=False)
    business_fit_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    confidence_level: Mapped[str] = mapped_column(String(64), nullable=False)
    completeness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    tco_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("tco_result.id", ondelete="RESTRICT"),
        index=True,
    )
    hard_block_count: Mapped[int] = mapped_column(nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(nullable=False, default=0)
    rank: Mapped[int | None] = mapped_column(index=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    assumptions: Mapped[list[str] | None] = mapped_column(JSON)
    key_strength_conditions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    key_risks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    missing_information: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate_decision_result.id", ondelete="SET NULL"),
        index=True,
    )
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    output_level: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    decision_run: Mapped[DecisionRun] = relationship(back_populates="results")
    mapping_candidate: Mapped[MappingCandidate] = relationship()
    provider: Mapped[Provider] = relationship()
    tco_result: Mapped[TCOResult | None] = relationship()
    superseded_by: Mapped[CandidateDecisionResult | None] = relationship(
        remote_side="CandidateDecisionResult.id"
    )
    dimension_scores: Mapped[list[DimensionScore]] = relationship(back_populates="candidate_result")
    rule_evaluations: Mapped[list[RuleEvaluation]] = relationship(back_populates="candidate_result")
    reviews: Mapped[list[DecisionReview]] = relationship(back_populates="candidate_result")


class DimensionScore(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "candidate_result_id",
            "dimension",
            name="uq_dimension_score_result_dimension",
        ),
        CheckConstraint(
            f"dimension IN ({sql_in_values(ScoringDimension.values())})",
            name="dimension_score_dimension",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(DimensionScoreStatus.values())})",
            name="dimension_score_status",
        ),
        CheckConstraint(
            "raw_score IS NULL OR (raw_score >= 0 AND raw_score <= 1)",
            name="dimension_score_raw",
        ),
        CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 1)",
            name="dimension_score_normalized",
        ),
        CheckConstraint("weight >= 0 AND weight <= 1", name="dimension_score_weight"),
        CheckConstraint(
            "weighted_score IS NULL OR (weighted_score >= 0 AND weighted_score <= 1)",
            name="dimension_score_weighted",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="dimension_score_confidence"),
        CheckConstraint(
            "completeness >= 0 AND completeness <= 1", name="dimension_score_completeness"
        ),
    )

    candidate_result_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_decision_result.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    normalized_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    weighted_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    completeness: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_package_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence_package.id", ondelete="RESTRICT"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    candidate_result: Mapped[CandidateDecisionResult] = relationship(
        back_populates="dimension_scores"
    )
    evidence_package: Mapped[EvidencePackage | None] = relationship()


class RuleEvaluation(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "candidate_result_id",
            "scoring_rule_id",
            "requirement_id",
            name="uq_rule_evaluation_identity",
        ),
        CheckConstraint(
            f"result_status IN ({sql_in_values(RuleEvaluationStatus.values())})",
            name="rule_evaluation_status",
        ),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="rule_score"),
    )

    candidate_result_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_decision_result.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scoring_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("scoring_rule.id", ondelete="RESTRICT"),
        index=True,
    )
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenario_requirement.id", ondelete="RESTRICT"),
        index=True,
    )
    observed_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    expected_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_status: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    hard_block: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocking_reason: Mapped[str | None] = mapped_column(Text)
    evidence_reference_ids: Mapped[list[int] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    candidate_result: Mapped[CandidateDecisionResult] = relationship(
        back_populates="rule_evaluations"
    )
    scoring_rule: Mapped[ScoringRule | None] = relationship()
    requirement: Mapped[ScenarioRequirement | None] = relationship()


class DecisionReview(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"decision IN ({sql_in_values(DecisionReviewStatus.values())})",
            name="decision_review_decision",
        ),
        CheckConstraint(
            "decision <> 'customer_approved'",
            name="decision_review_no_auto_customer_approval",
        ),
    )

    candidate_result_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_decision_result.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    accepted_assumptions: Mapped[list[str] | None] = mapped_column(JSON)
    rejected_assumptions: Mapped[list[str] | None] = mapped_column(JSON)
    corrected_weights: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    corrected_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    approved_scope: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    expiration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    candidate_result: Mapped[CandidateDecisionResult] = relationship(back_populates="reviews")


class DecisionSensitivityResult(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "decision_run_id",
            "analysis_code",
            name="uq_decision_sensitivity_run_analysis",
        ),
        CheckConstraint(
            f"sensitivity_status IN ({sql_in_values(SensitivityStatus.values())})",
            name="decision_sensitivity_status",
        ),
        CheckConstraint("score_variance >= 0", name="decision_sensitivity_variance"),
        CheckConstraint("top_candidate_change_count >= 0", name="decision_sensitivity_top_changes"),
        CheckConstraint(
            "critical_assumption_count >= 0",
            name="decision_sensitivity_critical_assumptions",
        ),
    )

    decision_run_id: Mapped[int] = mapped_column(
        ForeignKey("decision_run.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    analysis_code: Mapped[str] = mapped_column(String(160), nullable=False)
    ranking_stability: Mapped[str] = mapped_column(String(64), nullable=False)
    score_variance: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    top_candidate_change_count: Mapped[int] = mapped_column(nullable=False, default=0)
    critical_assumption_count: Mapped[int] = mapped_column(nullable=False, default=0)
    sensitivity_status: Mapped[str] = mapped_column(String(64), nullable=False)
    scenarios_tested: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    decision_run: Mapped[DecisionRun] = relationship()
