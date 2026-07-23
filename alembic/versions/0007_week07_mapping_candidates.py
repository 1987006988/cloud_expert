"""Add week 7 mapping candidate models.

Revision ID: 0007_week07_mapping_candidates
Revises: 0006_week06_canonical_normalization
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_week07_mapping_candidates"
down_revision: str | None = "0006_week06_canonical_normalization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MAPPING_LEVELS = (
    "'category', 'product', 'product_family', 'sku', 'service_tier', 'feature', "
    "'region_candidate', 'scenario_candidate', 'scenario'"
)
RULE_SET_STATUSES = "'active', 'deprecated', 'draft'"
RELATIONSHIP_TYPES = (
    "'equivalent_category', 'same_service_class', 'close_alternative', "
    "'partial_overlap', 'migration_target_candidate', 'feature_overlap', "
    "'no_direct_equivalent', 'deprecated_replacement_candidate', 'unknown'"
)
CANDIDATE_STATUSES = (
    "'candidate', 'pending_review', 'approved', 'corrected', 'rejected', "
    "'superseded', 'not_comparable', 'insufficient_evidence'"
)
REVIEW_STATUSES = "'machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown'"
EVIDENCE_ROLES = (
    "'source_field', 'target_field', 'category_positioning', 'availability', "
    "'exclusion', 'lifecycle', 'sla_context'"
)
FIELD_STATUSES = (
    "'match', 'close', 'different', 'missing_source', 'missing_target', "
    "'qualitative_only', 'not_comparable', 'insufficient_evidence'"
)


def upgrade() -> None:
    op.create_table(
        "mapping_rule_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_set_code", sa.String(length=160), nullable=False),
        sa.Column("rule_set_version", sa.String(length=64), nullable=False),
        sa.Column("mapping_level", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("market_mode", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("required_fields", sa.JSON(), nullable=True),
        sa.Column("optional_fields", sa.JSON(), nullable=True),
        sa.Column("exclusion_rules", sa.JSON(), nullable=True),
        sa.Column("scoring_config", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"mapping_level IN ({MAPPING_LEVELS})", name="mapping_rule_set_level"),
        sa.CheckConstraint(f"status IN ({RULE_SET_STATUSES})", name="mapping_rule_set_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_set_code", "rule_set_version", name="uq_mapping_rule_set_version"
        ),
    )
    op.create_index("ix_mapping_rule_set_rule_set_code", "mapping_rule_set", ["rule_set_code"])

    op.create_table(
        "mapping_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mapping_level", sa.String(length=64), nullable=False),
        sa.Column("source_provider_id", sa.Integer(), nullable=False),
        sa.Column("source_entity_type", sa.String(length=64), nullable=False),
        sa.Column("source_entity_id", sa.Integer(), nullable=False),
        sa.Column("target_provider_id", sa.Integer(), nullable=False),
        sa.Column("target_entity_type", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("candidate_status", sa.String(length=64), nullable=False),
        sa.Column("rule_set_id", sa.Integer(), nullable=False),
        sa.Column("raw_score", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("normalized_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("blocking_reasons", sa.JSON(), nullable=True),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"mapping_level IN ({MAPPING_LEVELS})", name="mapping_candidate_level"),
        sa.CheckConstraint(
            f"relationship_type IN ({RELATIONSHIP_TYPES})",
            name="mapping_candidate_relationship_type",
        ),
        sa.CheckConstraint(
            f"candidate_status IN ({CANDIDATE_STATUSES})", name="mapping_candidate_status"
        ),
        sa.CheckConstraint(
            f"review_status IN ({REVIEW_STATUSES})", name="mapping_candidate_review_status"
        ),
        sa.CheckConstraint(
            "raw_score IS NULL OR (raw_score >= 0 AND raw_score <= 100)",
            name="mapping_candidate_raw_score",
        ),
        sa.CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 1)",
            name="mapping_candidate_normalized_score",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="mapping_candidate_confidence",
        ),
        sa.ForeignKeyConstraint(["rule_set_id"], ["mapping_rule_set.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_provider_id"], ["provider.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["mapping_candidate.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["target_provider_id"], ["provider.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_set_id",
            "source_entity_type",
            "source_entity_id",
            "target_entity_type",
            "target_entity_id",
            "mapping_level",
            name="uq_mapping_candidate_natural_key",
        ),
    )
    for column in [
        "mapping_level",
        "source_provider_id",
        "source_entity_id",
        "target_provider_id",
        "target_entity_id",
        "rule_set_id",
        "superseded_by_id",
    ]:
        op.create_index(f"ix_mapping_candidate_{column}", "mapping_candidate", [column])

    op.create_table(
        "mapping_candidate_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mapping_candidate_id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("evidence_role", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"evidence_role IN ({EVIDENCE_ROLES})", name="mapping_candidate_evidence_role"
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["mapping_candidate_id"], ["mapping_candidate.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mapping_candidate_id",
            "evidence_id",
            "evidence_role",
            name="uq_mapping_candidate_evidence_role",
        ),
    )
    op.create_index(
        "ix_mapping_candidate_evidence_evidence_id", "mapping_candidate_evidence", ["evidence_id"]
    )
    op.create_index(
        "ix_mapping_candidate_evidence_mapping_candidate_id",
        "mapping_candidate_evidence",
        ["mapping_candidate_id"],
    )

    op.create_table(
        "mapping_field_comparison",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mapping_candidate_id", sa.Integer(), nullable=False),
        sa.Column("canonical_field_id", sa.Integer(), nullable=False),
        sa.Column("source_value_id", sa.Integer(), nullable=True),
        sa.Column("target_value_id", sa.Integer(), nullable=True),
        sa.Column("semantic_status", sa.String(length=64), nullable=False),
        sa.Column("unit_status", sa.String(length=64), nullable=False),
        sa.Column("scope_status", sa.String(length=64), nullable=False),
        sa.Column("qualifier_status", sa.String(length=64), nullable=False),
        sa.Column("freshness_status", sa.String(length=64), nullable=False),
        sa.Column("evidence_status", sa.String(length=64), nullable=False),
        sa.Column("comparison_status", sa.String(length=64), nullable=False),
        sa.Column("similarity_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("blocking_reason", sa.Text(), nullable=True),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"semantic_status IN ({FIELD_STATUSES})", name="mapping_field_semantic_status"
        ),
        sa.CheckConstraint(f"unit_status IN ({FIELD_STATUSES})", name="mapping_field_unit_status"),
        sa.CheckConstraint(
            f"scope_status IN ({FIELD_STATUSES})", name="mapping_field_scope_status"
        ),
        sa.CheckConstraint(
            f"qualifier_status IN ({FIELD_STATUSES})", name="mapping_field_qualifier_status"
        ),
        sa.CheckConstraint(
            f"evidence_status IN ({FIELD_STATUSES})", name="mapping_field_evidence_status"
        ),
        sa.CheckConstraint(
            f"comparison_status IN ({FIELD_STATUSES})", name="mapping_field_comparison_status"
        ),
        sa.CheckConstraint(
            "similarity_score IS NULL OR (similarity_score >= 0 AND similarity_score <= 1)",
            name="mapping_field_similarity_score",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_field_id"], ["canonical_field_definition.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["mapping_candidate_id"], ["mapping_candidate.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_value_id"], ["normalized_specification.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_value_id"], ["normalized_specification.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mapping_candidate_id",
            "canonical_field_id",
            "source_value_id",
            "target_value_id",
            name="uq_mapping_field_comparison_identity",
        ),
    )
    for column in [
        "mapping_candidate_id",
        "canonical_field_id",
        "source_value_id",
        "target_value_id",
    ]:
        op.create_index(
            f"ix_mapping_field_comparison_{column}", "mapping_field_comparison", [column]
        )

    op.create_table(
        "mapping_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mapping_candidate_id", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("reviewer", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("corrected_relationship_type", sa.String(length=64), nullable=True),
        sa.Column("corrected_target_entity_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"review_status IN ({REVIEW_STATUSES})", name="mapping_review_status"),
        sa.CheckConstraint(
            "corrected_relationship_type IS NULL "
            f"OR corrected_relationship_type IN ({RELATIONSHIP_TYPES})",
            name="mapping_review_corrected_relationship_type",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_candidate_id"], ["mapping_candidate.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mapping_review_mapping_candidate_id", "mapping_review", ["mapping_candidate_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mapping_review_mapping_candidate_id", table_name="mapping_review")
    op.drop_table("mapping_review")

    for column in [
        "target_value_id",
        "source_value_id",
        "canonical_field_id",
        "mapping_candidate_id",
    ]:
        op.drop_index(
            f"ix_mapping_field_comparison_{column}", table_name="mapping_field_comparison"
        )
    op.drop_table("mapping_field_comparison")

    op.drop_index(
        "ix_mapping_candidate_evidence_mapping_candidate_id",
        table_name="mapping_candidate_evidence",
    )
    op.drop_index(
        "ix_mapping_candidate_evidence_evidence_id", table_name="mapping_candidate_evidence"
    )
    op.drop_table("mapping_candidate_evidence")

    for column in [
        "superseded_by_id",
        "rule_set_id",
        "target_entity_id",
        "target_provider_id",
        "source_entity_id",
        "source_provider_id",
        "mapping_level",
    ]:
        op.drop_index(f"ix_mapping_candidate_{column}", table_name="mapping_candidate")
    op.drop_table("mapping_candidate")

    op.drop_index("ix_mapping_rule_set_rule_set_code", table_name="mapping_rule_set")
    op.drop_table("mapping_rule_set")
