"""Add week 6 canonical normalization models.

Revision ID: 0006_week06_canonical_normalization
Revises: 0005_week05_aliyun_zone_availability
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_week06_canonical_normalization"
down_revision: str | None = "0005_week05_aliyun_zone_availability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CANONICAL_DOMAINS = (
    "'compute', 'object_storage', 'region', 'sla', 'product_metadata'"
)
DATA_TYPES = "'numeric', 'text', 'boolean', 'enum'"
VALUE_QUALIFIERS = (
    "'exact', 'baseline', 'maximum', 'minimum', 'designed', 'supported', "
    "'official_name', 'description', 'unknown'"
)
SCOPE_TYPES = (
    "'product', 'sku', 'product_family', 'service_tier', 'region', 'zone', 'sla', 'unknown'"
)
RULE_TYPES = (
    "'field_mapping', 'unit_conversion', 'qualifier_inference', "
    "'scope_inference', 'quality_scoring'"
)
RUN_STATUSES = "'succeeded', 'partial', 'failed'"
REVIEW_STATUSES = (
    "'machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown'"
)
COMPARABILITY_STATUSES = "'comparable', 'partial', 'not_comparable', 'needs_review'"


def upgrade() -> None:
    op.create_table(
        "canonical_field_definition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("canonical_unit", sa.String(length=64), nullable=True),
        sa.Column("unit_dimension", sa.String(length=64), nullable=True),
        sa.Column("default_qualifier", sa.String(length=64), nullable=False),
        sa.Column("default_scope_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_comparable", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"domain IN ({CANONICAL_DOMAINS})", name="canonical_field_definition_domain"),
        sa.CheckConstraint(f"data_type IN ({DATA_TYPES})", name="canonical_field_definition_data_type"),
        sa.CheckConstraint(
            f"default_qualifier IN ({VALUE_QUALIFIERS})",
            name="canonical_field_definition_default_qualifier",
        ),
        sa.CheckConstraint(
            f"default_scope_type IN ({SCOPE_TYPES})",
            name="canonical_field_definition_default_scope",
        ),
        sa.ForeignKeyConstraint(["category_id"], ["product_category.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_canonical_field_definition_code"),
    )
    op.create_index(
        "ix_canonical_field_definition_category_id",
        "canonical_field_definition",
        ["category_id"],
    )
    op.create_index(
        "ix_canonical_field_definition_code",
        "canonical_field_definition",
        ["code"],
    )
    op.create_index(
        "ix_canonical_field_definition_domain",
        "canonical_field_definition",
        ["domain"],
    )

    op.create_table(
        "normalization_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("rule_type", sa.String(length=64), nullable=False),
        sa.Column("source_field_code", sa.String(length=160), nullable=True),
        sa.Column("canonical_field_id", sa.Integer(), nullable=True),
        sa.Column("source_unit", sa.String(length=64), nullable=True),
        sa.Column("canonical_unit", sa.String(length=64), nullable=True),
        sa.Column("value_qualifier", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"rule_type IN ({RULE_TYPES})", name="normalization_rule_type"),
        sa.CheckConstraint(
            f"value_qualifier IN ({VALUE_QUALIFIERS})",
            name="normalization_rule_value_qualifier",
        ),
        sa.CheckConstraint(f"scope_type IN ({SCOPE_TYPES})", name="normalization_rule_scope_type"),
        sa.ForeignKeyConstraint(
            ["canonical_field_id"],
            ["canonical_field_definition.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_normalization_rule_code_version"),
    )
    op.create_index(
        "ix_normalization_rule_canonical_field_id",
        "normalization_rule",
        ["canonical_field_id"],
    )
    op.create_index("ix_normalization_rule_code", "normalization_rule", ["code"])
    op.create_index(
        "ix_normalization_rule_source_field_code",
        "normalization_rule",
        ["source_field_code"],
    )

    op.create_table(
        "normalization_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_database_label", sa.String(length=256), nullable=True),
        sa.Column("product_filter", sa.String(length=256), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_examined", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("records_skipped", sa.Integer(), nullable=False),
        sa.Column("review_items_created", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="normalization_run_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_normalization_run_key"),
    )
    op.create_index("ix_normalization_run_run_key", "normalization_run", ["run_key"])

    op.create_table(
        "normalized_specification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_specification_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("canonical_field_id", sa.Integer(), nullable=False),
        sa.Column("normalization_rule_id", sa.Integer(), nullable=False),
        sa.Column("normalization_run_id", sa.Integer(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=64), nullable=False),
        sa.Column("scope_identity", sa.String(length=256), nullable=False),
        sa.Column("value_qualifier", sa.String(length=64), nullable=False),
        sa.Column("numeric_value", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("boolean_value", sa.Boolean(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("raw_unit", sa.String(length=64), nullable=True),
        sa.Column("canonical_value", sa.String(length=256), nullable=True),
        sa.Column("canonical_unit", sa.String(length=64), nullable=True),
        sa.Column("conversion_notes", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("source_value_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(CASE WHEN numeric_value IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN text_value IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN boolean_value IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="normalized_specification_exactly_one_value",
        ),
        sa.CheckConstraint(f"scope_type IN ({SCOPE_TYPES})", name="normalized_specification_scope_type"),
        sa.CheckConstraint(
            f"value_qualifier IN ({VALUE_QUALIFIERS})",
            name="normalized_specification_value_qualifier",
        ),
        sa.CheckConstraint(
            f"review_status IN ({REVIEW_STATUSES})",
            name="normalized_specification_review_status",
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="normalized_specification_quality_score",
        ),
        sa.ForeignKeyConstraint(["canonical_field_id"], ["canonical_field_definition.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["normalization_rule_id"], ["normalization_rule.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["normalization_run_id"], ["normalization_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_specification_id"], ["product_specification.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku_id"], ["sku.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_specification_id",
            "canonical_field_id",
            "scope_type",
            "scope_identity",
            "value_qualifier",
            name="uq_normalized_specification_identity",
        ),
    )
    op.create_index(
        "ix_normalized_specification_canonical_field_id",
        "normalized_specification",
        ["canonical_field_id"],
    )
    op.create_index("ix_normalized_specification_evidence_id", "normalized_specification", ["evidence_id"])
    op.create_index(
        "ix_normalized_specification_normalization_rule_id",
        "normalized_specification",
        ["normalization_rule_id"],
    )
    op.create_index(
        "ix_normalized_specification_normalization_run_id",
        "normalized_specification",
        ["normalization_run_id"],
    )
    op.create_index("ix_normalized_specification_product_id", "normalized_specification", ["product_id"])
    op.create_index(
        "ix_normalized_specification_product_specification_id",
        "normalized_specification",
        ["product_specification_id"],
    )
    op.create_index("ix_normalized_specification_sku_id", "normalized_specification", ["sku_id"])
    op.create_index(
        "ix_normalized_specification_source_value_hash",
        "normalized_specification",
        ["source_value_hash"],
    )

    op.create_table(
        "comparability_assessment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("canonical_field_id", sa.Integer(), nullable=False),
        sa.Column("source_product_id", sa.Integer(), nullable=False),
        sa.Column("target_product_id", sa.Integer(), nullable=False),
        sa.Column("normalization_run_id", sa.Integer(), nullable=True),
        sa.Column("scope_type", sa.String(length=64), nullable=False),
        sa.Column("value_qualifier", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("market_scope", sa.String(length=128), nullable=True),
        sa.Column("evidence_coverage_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("unit_compatibility_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("qualifier_compatibility_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("scope_compatibility_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("overall_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"status IN ({COMPARABILITY_STATUSES})",
            name="comparability_assessment_status",
        ),
        sa.CheckConstraint(
            f"scope_type IN ({SCOPE_TYPES})",
            name="comparability_assessment_scope_type",
        ),
        sa.CheckConstraint(
            f"value_qualifier IN ({VALUE_QUALIFIERS})",
            name="comparability_assessment_value_qualifier",
        ),
        sa.CheckConstraint(
            f"review_status IN ({REVIEW_STATUSES})",
            name="comparability_assessment_review_status",
        ),
        sa.CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 1)",
            name="comparability_assessment_overall_score",
        ),
        sa.ForeignKeyConstraint(["canonical_field_id"], ["canonical_field_definition.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["normalization_run_id"], ["normalization_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_field_id",
            "source_product_id",
            "target_product_id",
            "scope_type",
            "value_qualifier",
            name="uq_comparability_assessment_identity",
        ),
    )
    op.create_index(
        "ix_comparability_assessment_canonical_field_id",
        "comparability_assessment",
        ["canonical_field_id"],
    )
    op.create_index(
        "ix_comparability_assessment_normalization_run_id",
        "comparability_assessment",
        ["normalization_run_id"],
    )
    op.create_index(
        "ix_comparability_assessment_source_product_id",
        "comparability_assessment",
        ["source_product_id"],
    )
    op.create_index(
        "ix_comparability_assessment_target_product_id",
        "comparability_assessment",
        ["target_product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_comparability_assessment_target_product_id", table_name="comparability_assessment")
    op.drop_index("ix_comparability_assessment_source_product_id", table_name="comparability_assessment")
    op.drop_index("ix_comparability_assessment_normalization_run_id", table_name="comparability_assessment")
    op.drop_index("ix_comparability_assessment_canonical_field_id", table_name="comparability_assessment")
    op.drop_table("comparability_assessment")

    op.drop_index("ix_normalized_specification_source_value_hash", table_name="normalized_specification")
    op.drop_index("ix_normalized_specification_sku_id", table_name="normalized_specification")
    op.drop_index("ix_normalized_specification_product_specification_id", table_name="normalized_specification")
    op.drop_index("ix_normalized_specification_product_id", table_name="normalized_specification")
    op.drop_index("ix_normalized_specification_normalization_run_id", table_name="normalized_specification")
    op.drop_index("ix_normalized_specification_normalization_rule_id", table_name="normalized_specification")
    op.drop_index("ix_normalized_specification_evidence_id", table_name="normalized_specification")
    op.drop_index("ix_normalized_specification_canonical_field_id", table_name="normalized_specification")
    op.drop_table("normalized_specification")

    op.drop_index("ix_normalization_run_run_key", table_name="normalization_run")
    op.drop_table("normalization_run")

    op.drop_index("ix_normalization_rule_source_field_code", table_name="normalization_rule")
    op.drop_index("ix_normalization_rule_code", table_name="normalization_rule")
    op.drop_index("ix_normalization_rule_canonical_field_id", table_name="normalization_rule")
    op.drop_table("normalization_rule")

    op.drop_index("ix_canonical_field_definition_domain", table_name="canonical_field_definition")
    op.drop_index("ix_canonical_field_definition_code", table_name="canonical_field_definition")
    op.drop_index("ix_canonical_field_definition_category_id", table_name="canonical_field_definition")
    op.drop_table("canonical_field_definition")
