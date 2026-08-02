"""Add week 10 scenario decision engine models.

Revision ID: 0010_week10_decision_engine
Revises: 0009_week09_pricing_tco
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_week10_decision_engine"
down_revision: str | None = "0009_week09_pricing_tco"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKET_MODES = "'domestic', 'international'"
SCENARIO_TYPES = (
    "'compute_general', 'compute_high_performance', 'memory_intensive', 'gpu_training', "
    "'gpu_inference', 'business_critical_compute', 'object_storage_frequent_access', "
    "'object_storage_infrequent_access', 'object_storage_archive', 'global_application', "
    "'china_domestic_application', 'regulated_workload', 'cost_sensitive_workload', "
    "'migration_replacement', 'custom'"
)
SCENARIO_STATUS = "'draft', 'active', 'archived'"
REQUIREMENT_TYPES = (
    "'technical', 'availability', 'regional', 'compliance', 'reliability', 'operations', "
    "'migration', 'cost', 'evidence', 'review'"
)
REQUIREMENT_PRIORITY = "'mandatory', 'critical', 'high', 'medium', 'low', 'informational'"
OPERATORS = (
    "'equals', 'not_equals', 'greater_than', 'greater_than_or_equal', 'less_than', "
    "'less_than_or_equal', 'between', 'in', 'not_in', 'contains', 'supports', "
    "'does_not_support', 'same_country', 'same_geography', 'customer_eligible', "
    "'evidence_at_least', 'freshness_at_least'"
)
MISSING_POLICY = (
    "'block', 'requires_review', 'exclude_dimension', 'penalize_confidence', "
    "'use_conservative_bound', 'informational_only'"
)
POLICY_STATUS = "'draft', 'active', 'deprecated'"
DIMENSIONS = (
    "'technical_fit', 'availability_fit', 'regional_fit', 'compliance_fit', "
    "'reliability_fit', 'operability_fit', 'migration_fit', 'cost_fit', "
    "'evidence_quality', 'data_freshness', 'review_readiness'"
)
SCORE_FUNCTIONS = (
    "'exact_match', 'boolean_match', 'range_fit', 'ratio_fit', 'threshold_fit', "
    "'categorical_fit', 'tiered_fit', 'completeness_fit', 'freshness_fit', "
    "'evidence_fit', 'custom_registered'"
)
RUN_STATUS = "'succeeded', 'partial', 'failed', 'dry_run'"
DECISION_STATUS = (
    "'eligible', 'conditionally_eligible', 'blocked', 'insufficient_evidence', "
    "'incomplete_cost', 'requires_review', 'stale_data', 'invalid_mapping', 'superseded'"
)
CONFIDENCE_LEVELS = "'high', 'medium', 'low', 'insufficient'"
DIMENSION_STATUS = "'scored', 'excluded', 'insufficient_evidence', 'blocked', 'requires_review'"
RULE_STATUS = "'pass', 'fail', 'missing_data', 'not_applicable', 'requires_review'"
REVIEW_STATUS = (
    "'machine_generated', 'internally_approved', 'rejected', 'corrected', 'customer_approved'"
)
OUTPUT_LEVELS = "'internal_only', 'customer_eligible_candidate'"
SENSITIVITY_STATUS = "'stable', 'moderately_sensitive', 'highly_sensitive', 'indeterminate'"


def upgrade() -> None:
    op.create_table(
        "scoring_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("policy_code", sa.String(length=160), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("scenario_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dimension_weights", sa.JSON(), nullable=False),
        sa.Column("hard_block_rules", sa.JSON(), nullable=True),
        sa.Column("missing_data_policy", sa.JSON(), nullable=False),
        sa.Column("confidence_policy", sa.JSON(), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"scenario_type IN ({SCENARIO_TYPES})", name="scoring_policy_scenario_type"
        ),
        sa.CheckConstraint(f"status IN ({POLICY_STATUS})", name="scoring_policy_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_code", "policy_version", name="uq_scoring_policy_version"),
    )
    op.create_index("ix_scoring_policy_policy_code", "scoring_policy", ["policy_code"])

    op.create_table(
        "decision_scenario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_code", sa.String(length=160), nullable=False),
        sa.Column("scenario_version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scenario_type", sa.String(length=64), nullable=False),
        sa.Column("market_mode", sa.String(length=64), nullable=False),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("preferred_regions", sa.JSON(), nullable=True),
        sa.Column("workload_profile", sa.JSON(), nullable=False),
        sa.Column("technical_requirements", sa.JSON(), nullable=True),
        sa.Column("availability_requirements", sa.JSON(), nullable=True),
        sa.Column("compliance_requirements", sa.JSON(), nullable=True),
        sa.Column("data_residency_requirements", sa.JSON(), nullable=True),
        sa.Column("operational_requirements", sa.JSON(), nullable=True),
        sa.Column("migration_requirements", sa.JSON(), nullable=True),
        sa.Column("budget_preferences", sa.JSON(), nullable=True),
        sa.Column("scoring_policy_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"scenario_type IN ({SCENARIO_TYPES})", name="decision_scenario_type"),
        sa.CheckConstraint(
            f"market_mode IN ({MARKET_MODES})", name="decision_scenario_market_mode"
        ),
        sa.CheckConstraint(f"status IN ({SCENARIO_STATUS})", name="decision_scenario_status"),
        sa.ForeignKeyConstraint(["scoring_policy_id"], ["scoring_policy.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_code", "scenario_version", name="uq_decision_scenario_version"
        ),
    )
    op.create_index("ix_decision_scenario_scenario_code", "decision_scenario", ["scenario_code"])
    op.create_index("ix_decision_scenario_scenario_type", "decision_scenario", ["scenario_type"])
    op.create_index(
        "ix_decision_scenario_scoring_policy_id", "decision_scenario", ["scoring_policy_id"]
    )

    op.create_table(
        "scenario_requirement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("requirement_code", sa.String(length=160), nullable=False),
        sa.Column("requirement_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_field_id", sa.Integer(), nullable=True),
        sa.Column("operator", sa.String(length=64), nullable=False),
        sa.Column("required_value", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("qualifier", sa.String(length=64), nullable=True),
        sa.Column("scope", sa.String(length=64), nullable=True),
        sa.Column("priority", sa.String(length=64), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("missing_data_policy", sa.String(length=64), nullable=False),
        sa.Column("evidence_requirement", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"requirement_type IN ({REQUIREMENT_TYPES})", name="scenario_requirement_type"
        ),
        sa.CheckConstraint(f"operator IN ({OPERATORS})", name="scenario_requirement_operator"),
        sa.CheckConstraint(
            f"priority IN ({REQUIREMENT_PRIORITY})", name="scenario_requirement_priority"
        ),
        sa.CheckConstraint(
            f"missing_data_policy IN ({MISSING_POLICY})", name="scenario_requirement_missing_policy"
        ),
        sa.ForeignKeyConstraint(
            ["canonical_field_id"], ["canonical_field_definition.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["decision_scenario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario_id", "requirement_code", name="uq_scenario_requirement_code"),
    )
    op.create_index("ix_scenario_requirement_scenario_id", "scenario_requirement", ["scenario_id"])
    op.create_index(
        "ix_scenario_requirement_canonical_field_id", "scenario_requirement", ["canonical_field_id"]
    )

    op.create_table(
        "scoring_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("rule_code", sa.String(length=160), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.String(length=64), nullable=False),
        sa.Column("canonical_field_id", sa.Integer(), nullable=True),
        sa.Column("operator", sa.String(length=64), nullable=False),
        sa.Column("expected_value", sa.JSON(), nullable=True),
        sa.Column("minimum_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("maximum_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("score_function", sa.String(length=64), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("evidence_requirement", sa.JSON(), nullable=True),
        sa.Column("missing_data_policy", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"dimension IN ({DIMENSIONS})", name="scoring_rule_dimension"),
        sa.CheckConstraint(f"operator IN ({OPERATORS})", name="scoring_rule_operator"),
        sa.CheckConstraint(
            f"score_function IN ({SCORE_FUNCTIONS})", name="scoring_rule_score_function"
        ),
        sa.CheckConstraint(
            f"missing_data_policy IN ({MISSING_POLICY})", name="scoring_rule_missing_policy"
        ),
        sa.CheckConstraint(f"status IN ({POLICY_STATUS})", name="scoring_rule_status"),
        sa.CheckConstraint(
            "minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 1)",
            name="scoring_rule_min_score",
        ),
        sa.CheckConstraint(
            "maximum_score IS NULL OR (maximum_score >= 0 AND maximum_score <= 1)",
            name="scoring_rule_max_score",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_field_id"], ["canonical_field_definition.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["policy_id"], ["scoring_policy.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id", "rule_code", "rule_version", name="uq_scoring_rule_version"
        ),
    )
    op.create_index("ix_scoring_rule_policy_id", "scoring_rule", ["policy_id"])
    op.create_index("ix_scoring_rule_canonical_field_id", "scoring_rule", ["canonical_field_id"])

    op.create_table(
        "decision_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_code", sa.String(length=160), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("scenario_version", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("mapping_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"status IN ({RUN_STATUS})", name="decision_run_status"),
        sa.CheckConstraint("candidate_count >= 0", name="decision_run_candidate_count"),
        sa.CheckConstraint("eligible_count >= 0", name="decision_run_eligible_count"),
        sa.CheckConstraint("blocked_count >= 0", name="decision_run_blocked_count"),
        sa.CheckConstraint("review_count >= 0", name="decision_run_review_count"),
        sa.CheckConstraint("warning_count >= 0", name="decision_run_warning_count"),
        sa.ForeignKeyConstraint(["policy_id"], ["scoring_policy.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scenario_id"], ["decision_scenario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_code", name="uq_decision_run_code"),
        sa.UniqueConstraint(
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
    )
    for column in ["run_code", "scenario_id", "policy_id"]:
        op.create_index(f"ix_decision_run_{column}", "decision_run", [column])

    op.create_table(
        "candidate_decision_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_run_id", sa.Integer(), nullable=False),
        sa.Column("mapping_candidate_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("decision_status", sa.String(length=64), nullable=False),
        sa.Column("business_fit_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("confidence_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("confidence_level", sa.String(length=64), nullable=False),
        sa.Column("completeness_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("match_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("tco_result_id", sa.Integer(), nullable=True),
        sa.Column("hard_block_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column("key_strength_conditions", sa.JSON(), nullable=True),
        sa.Column("key_risks", sa.JSON(), nullable=True),
        sa.Column("missing_information", sa.JSON(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("output_level", sa.String(length=64), nullable=False),
        sa.Column("customer_eligible", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"decision_status IN ({DECISION_STATUS})", name="candidate_decision_status"
        ),
        sa.CheckConstraint(
            f"confidence_level IN ({CONFIDENCE_LEVELS})", name="candidate_decision_confidence_level"
        ),
        sa.CheckConstraint(
            f"review_status IN ({REVIEW_STATUS})", name="candidate_decision_review_status"
        ),
        sa.CheckConstraint(
            f"output_level IN ({OUTPUT_LEVELS})", name="candidate_decision_output_level"
        ),
        sa.CheckConstraint(
            "business_fit_score IS NULL OR (business_fit_score >= 0 AND business_fit_score <= 1)",
            name="candidate_decision_business_fit_score",
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="candidate_decision_confidence_score",
        ),
        sa.CheckConstraint(
            "completeness_score IS NULL OR (completeness_score >= 0 AND completeness_score <= 1)",
            name="candidate_decision_completeness_score",
        ),
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="candidate_decision_match_score",
        ),
        sa.CheckConstraint("hard_block_count >= 0", name="candidate_decision_hard_blocks"),
        sa.CheckConstraint("warning_count >= 0", name="candidate_decision_warning_count"),
        sa.ForeignKeyConstraint(["decision_run_id"], ["decision_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["mapping_candidate_id"], ["mapping_candidate.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["candidate_decision_result.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tco_result_id"], ["tco_result.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_run_id",
            "mapping_candidate_id",
            name="uq_candidate_decision_result_run_candidate",
        ),
    )
    for column in [
        "decision_run_id",
        "mapping_candidate_id",
        "provider_id",
        "entity_id",
        "tco_result_id",
        "rank",
        "superseded_by_id",
    ]:
        op.create_index(
            f"ix_candidate_decision_result_{column}", "candidate_decision_result", [column]
        )

    op.create_table(
        "dimension_score",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_result_id", sa.Integer(), nullable=False),
        sa.Column("dimension", sa.String(length=64), nullable=False),
        sa.Column("raw_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("normalized_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("weighted_score", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("completeness", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence_package_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"dimension IN ({DIMENSIONS})", name="dimension_score_dimension"),
        sa.CheckConstraint(f"status IN ({DIMENSION_STATUS})", name="dimension_score_status"),
        sa.CheckConstraint(
            "raw_score IS NULL OR (raw_score >= 0 AND raw_score <= 1)", name="dimension_score_raw"
        ),
        sa.CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 1)",
            name="dimension_score_normalized",
        ),
        sa.CheckConstraint("weight >= 0 AND weight <= 1", name="dimension_score_weight"),
        sa.CheckConstraint(
            "weighted_score IS NULL OR (weighted_score >= 0 AND weighted_score <= 1)",
            name="dimension_score_weighted",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="dimension_score_confidence"
        ),
        sa.CheckConstraint(
            "completeness >= 0 AND completeness <= 1", name="dimension_score_completeness"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_result_id"], ["candidate_decision_result.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_package_id"], ["evidence_package.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_result_id", "dimension", name="uq_dimension_score_result_dimension"
        ),
    )
    op.create_index(
        "ix_dimension_score_candidate_result_id", "dimension_score", ["candidate_result_id"]
    )
    op.create_index(
        "ix_dimension_score_evidence_package_id", "dimension_score", ["evidence_package_id"]
    )

    op.create_table(
        "rule_evaluation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_result_id", sa.Integer(), nullable=False),
        sa.Column("scoring_rule_id", sa.Integer(), nullable=True),
        sa.Column("requirement_id", sa.Integer(), nullable=True),
        sa.Column("observed_value", sa.JSON(), nullable=True),
        sa.Column("expected_value", sa.JSON(), nullable=True),
        sa.Column("result_status", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("hard_block", sa.Boolean(), nullable=False),
        sa.Column("blocking_reason", sa.Text(), nullable=True),
        sa.Column("evidence_reference_ids", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"result_status IN ({RULE_STATUS})", name="rule_evaluation_status"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="rule_score"),
        sa.ForeignKeyConstraint(
            ["candidate_result_id"], ["candidate_decision_result.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["scenario_requirement.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["scoring_rule_id"], ["scoring_rule.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_result_id",
            "scoring_rule_id",
            "requirement_id",
            name="uq_rule_evaluation_identity",
        ),
    )
    for column in ["candidate_result_id", "scoring_rule_id", "requirement_id"]:
        op.create_index(f"ix_rule_evaluation_{column}", "rule_evaluation", [column])

    op.create_table(
        "decision_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_result_id", sa.Integer(), nullable=False),
        sa.Column("reviewer", sa.String(length=128), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("accepted_assumptions", sa.JSON(), nullable=True),
        sa.Column("rejected_assumptions", sa.JSON(), nullable=True),
        sa.Column("corrected_weights", sa.JSON(), nullable=True),
        sa.Column("corrected_requirements", sa.JSON(), nullable=True),
        sa.Column("approved_scope", sa.JSON(), nullable=True),
        sa.Column("expiration_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"decision IN ({REVIEW_STATUS})", name="decision_review_decision"),
        sa.CheckConstraint(
            "decision <> 'customer_approved'", name="decision_review_no_auto_customer_approval"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_result_id"], ["candidate_decision_result.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_review_candidate_result_id", "decision_review", ["candidate_result_id"]
    )

    op.create_table(
        "decision_sensitivity_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_run_id", sa.Integer(), nullable=False),
        sa.Column("analysis_code", sa.String(length=160), nullable=False),
        sa.Column("ranking_stability", sa.String(length=64), nullable=False),
        sa.Column("score_variance", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("top_candidate_change_count", sa.Integer(), nullable=False),
        sa.Column("critical_assumption_count", sa.Integer(), nullable=False),
        sa.Column("sensitivity_status", sa.String(length=64), nullable=False),
        sa.Column("scenarios_tested", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"sensitivity_status IN ({SENSITIVITY_STATUS})", name="decision_sensitivity_status"
        ),
        sa.CheckConstraint("score_variance >= 0", name="decision_sensitivity_variance"),
        sa.CheckConstraint(
            "top_candidate_change_count >= 0", name="decision_sensitivity_top_changes"
        ),
        sa.CheckConstraint(
            "critical_assumption_count >= 0", name="decision_sensitivity_critical_assumptions"
        ),
        sa.ForeignKeyConstraint(["decision_run_id"], ["decision_run.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_run_id", "analysis_code", name="uq_decision_sensitivity_run_analysis"
        ),
    )
    op.create_index(
        "ix_decision_sensitivity_result_decision_run_id",
        "decision_sensitivity_result",
        ["decision_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_sensitivity_result_decision_run_id", table_name="decision_sensitivity_result"
    )
    op.drop_table("decision_sensitivity_result")

    op.drop_index("ix_decision_review_candidate_result_id", table_name="decision_review")
    op.drop_table("decision_review")

    for column in ["requirement_id", "scoring_rule_id", "candidate_result_id"]:
        op.drop_index(f"ix_rule_evaluation_{column}", table_name="rule_evaluation")
    op.drop_table("rule_evaluation")

    op.drop_index("ix_dimension_score_evidence_package_id", table_name="dimension_score")
    op.drop_index("ix_dimension_score_candidate_result_id", table_name="dimension_score")
    op.drop_table("dimension_score")

    for column in [
        "superseded_by_id",
        "rank",
        "tco_result_id",
        "entity_id",
        "provider_id",
        "mapping_candidate_id",
        "decision_run_id",
    ]:
        op.drop_index(
            f"ix_candidate_decision_result_{column}", table_name="candidate_decision_result"
        )
    op.drop_table("candidate_decision_result")

    for column in ["policy_id", "scenario_id", "run_code"]:
        op.drop_index(f"ix_decision_run_{column}", table_name="decision_run")
    op.drop_table("decision_run")

    op.drop_index("ix_scoring_rule_canonical_field_id", table_name="scoring_rule")
    op.drop_index("ix_scoring_rule_policy_id", table_name="scoring_rule")
    op.drop_table("scoring_rule")

    op.drop_index("ix_scenario_requirement_canonical_field_id", table_name="scenario_requirement")
    op.drop_index("ix_scenario_requirement_scenario_id", table_name="scenario_requirement")
    op.drop_table("scenario_requirement")

    op.drop_index("ix_decision_scenario_scoring_policy_id", table_name="decision_scenario")
    op.drop_index("ix_decision_scenario_scenario_type", table_name="decision_scenario")
    op.drop_index("ix_decision_scenario_scenario_code", table_name="decision_scenario")
    op.drop_table("decision_scenario")

    op.drop_index("ix_scoring_policy_policy_code", table_name="scoring_policy")
    op.drop_table("scoring_policy")
