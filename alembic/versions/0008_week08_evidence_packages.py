"""Add week 8 evidence package models.

Revision ID: 0008_week08_evidence_packages
Revises: 0007_week07_mapping_candidates
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_week08_evidence_packages"
down_revision: str | None = "0007_week07_mapping_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PACKAGE_TYPES = (
    "'product_comparison', 'product_family_comparison', 'sku_comparison', "
    "'service_tier_comparison', 'field_comparison', 'mapping_review', "
    "'sla_context', 'availability_context'"
)
FRESHNESS = "'fresh', 'due_soon', 'stale', 'unknown', 'historical'"
REVIEWS = "'machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown'"
OUTPUT_LEVELS = "'internal_raw', 'internal_reviewed', 'customer_eligible', 'historical'"
RELIABILITY = (
    "'official_structured', 'official_specification', 'official_documentation', "
    "'official_sla', 'official_product_page', 'official_faq', 'official_release_note', "
    "'official_historical', 'manual_import_official', 'third_party', 'synthetic', "
    "'fixture', 'unknown'"
)
EVIDENCE_STATUS = (
    "'active', 'stale', 'superseded', 'conflicting', 'unavailable', 'unverifiable', "
    "'pending_review', 'rejected'"
)
RUN_STATUS = "'succeeded', 'partial', 'failed'"


def upgrade() -> None:
    op.create_table(
        "evidence_package",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_code", sa.String(length=160), nullable=False),
        sa.Column("package_version", sa.String(length=64), nullable=False),
        sa.Column("package_type", sa.String(length=64), nullable=False),
        sa.Column("market_mode", sa.String(length=64), nullable=False),
        sa.Column("source_entity_type", sa.String(length=64), nullable=False),
        sa.Column("source_entity_id", sa.Integer(), nullable=False),
        sa.Column("target_entity_type", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.Integer(), nullable=False),
        sa.Column("mapping_candidate_id", sa.Integer(), nullable=False),
        sa.Column("rule_set_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_status", sa.String(length=64), nullable=False),
        sa.Column("evidence_completeness", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("output_level", sa.String(length=64), nullable=False),
        sa.Column("customer_eligible", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"package_type IN ({PACKAGE_TYPES})", name="evidence_package_type"),
        sa.CheckConstraint(f"freshness_status IN ({FRESHNESS})", name="evidence_package_freshness"),
        sa.CheckConstraint(f"review_status IN ({REVIEWS})", name="evidence_package_review_status"),
        sa.CheckConstraint(
            f"output_level IN ({OUTPUT_LEVELS})", name="evidence_package_output_level"
        ),
        sa.CheckConstraint(
            "evidence_completeness IS NULL OR "
            "(evidence_completeness >= 0 AND evidence_completeness <= 1)",
            name="evidence_package_completeness",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_candidate_id"], ["mapping_candidate.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["evidence_package.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_code", "package_version", name="uq_evidence_package_version"),
    )
    for column in ["package_code", "source_entity_id", "target_entity_id", "mapping_candidate_id"]:
        op.create_index(f"ix_evidence_package_{column}", "evidence_package", [column])

    op.create_table(
        "evidence_reference",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_code", sa.String(length=160), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("locator", sa.String(length=512), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reliability_level", sa.String(length=64), nullable=False),
        sa.Column("evidence_status", sa.String(length=64), nullable=False),
        sa.Column("freshness_status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"reliability_level IN ({RELIABILITY})", name="evidence_reference_reliability"
        ),
        sa.CheckConstraint(
            f"evidence_status IN ({EVIDENCE_STATUS})", name="evidence_reference_status"
        ),
        sa.CheckConstraint(
            f"freshness_status IN ({FRESHNESS})", name="evidence_reference_freshness"
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshot_record.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id", name="uq_evidence_reference_evidence"),
        sa.UniqueConstraint("reference_code", name="uq_evidence_reference_code"),
    )
    op.create_index("ix_evidence_reference_evidence_id", "evidence_reference", ["evidence_id"])
    op.create_index(
        "ix_evidence_reference_reference_code", "evidence_reference", ["reference_code"]
    )
    op.create_index("ix_evidence_reference_snapshot_id", "evidence_reference", ["snapshot_id"])

    op.create_table(
        "evidence_package_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("canonical_field_id", sa.Integer(), nullable=True),
        sa.Column("source_value_id", sa.Integer(), nullable=True),
        sa.Column("target_value_id", sa.Integer(), nullable=True),
        sa.Column("comparability_assessment_id", sa.Integer(), nullable=True),
        sa.Column("source_evidence_id", sa.Integer(), nullable=True),
        sa.Column("target_evidence_id", sa.Integer(), nullable=True),
        sa.Column("source_reference_code", sa.String(length=160), nullable=True),
        sa.Column("target_reference_code", sa.String(length=160), nullable=True),
        sa.Column("comparison_status", sa.String(length=64), nullable=False),
        sa.Column("matched_status", sa.String(length=64), nullable=False),
        sa.Column("scope_status", sa.String(length=64), nullable=False),
        sa.Column("qualifier_status", sa.String(length=64), nullable=False),
        sa.Column("freshness_status", sa.String(length=64), nullable=False),
        sa.Column("conflict_status", sa.String(length=64), nullable=False),
        sa.Column("blocking_reason", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"freshness_status IN ({FRESHNESS})", name="evidence_package_item_freshness"
        ),
        sa.ForeignKeyConstraint(
            ["canonical_field_id"], ["canonical_field_definition.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["comparability_assessment_id"], ["comparability_assessment.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["package_id"], ["evidence_package.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_value_id"], ["normalized_specification.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["target_evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["target_value_id"], ["normalized_specification.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id",
            "canonical_field_id",
            "source_value_id",
            "target_value_id",
            "display_order",
            name="uq_evidence_package_item_identity",
        ),
    )
    for column in [
        "package_id",
        "canonical_field_id",
        "source_value_id",
        "target_value_id",
        "comparability_assessment_id",
        "source_evidence_id",
        "target_evidence_id",
    ]:
        op.create_index(f"ix_evidence_package_item_{column}", "evidence_package_item", [column])

    op.create_table(
        "evidence_package_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_code", sa.String(length=160), nullable=False),
        sa.Column("package_type", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("package_count", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("missing_evidence_count", sa.Integer(), nullable=False),
        sa.Column("stale_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(f"package_type IN ({PACKAGE_TYPES})", name="evidence_package_run_type"),
        sa.CheckConstraint(f"status IN ({RUN_STATUS})", name="evidence_package_run_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_code", name="uq_evidence_package_run_code"),
    )
    op.create_index("ix_evidence_package_run_run_code", "evidence_package_run", ["run_code"])


def downgrade() -> None:
    op.drop_index("ix_evidence_package_run_run_code", table_name="evidence_package_run")
    op.drop_table("evidence_package_run")

    for column in [
        "target_evidence_id",
        "source_evidence_id",
        "comparability_assessment_id",
        "target_value_id",
        "source_value_id",
        "canonical_field_id",
        "package_id",
    ]:
        op.drop_index(f"ix_evidence_package_item_{column}", table_name="evidence_package_item")
    op.drop_table("evidence_package_item")

    op.drop_index("ix_evidence_reference_snapshot_id", table_name="evidence_reference")
    op.drop_index("ix_evidence_reference_reference_code", table_name="evidence_reference")
    op.drop_index("ix_evidence_reference_evidence_id", table_name="evidence_reference")
    op.drop_table("evidence_reference")

    for column in ["mapping_candidate_id", "target_entity_id", "source_entity_id", "package_code"]:
        op.drop_index(f"ix_evidence_package_{column}", table_name="evidence_package")
    op.drop_table("evidence_package")
