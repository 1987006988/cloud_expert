"""Add week 3 parsing, review, SLA, and family models.

Revision ID: 0003_week03_parsing_models
Revises: 0002_ingestion_snapshots
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_week03_parsing_models"
down_revision: str | None = "0002_ingestion_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.add_column(sa.Column("page_title", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("snapshot_record_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("content_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("parser_rule", sa.String(length=128), nullable=True))
        batch_op.create_index("ix_evidence_snapshot_record_id", ["snapshot_record_id"])
        batch_op.create_foreign_key(
            "fk_evidence_snapshot_record_id_snapshot_record",
            "snapshot_record",
            ["snapshot_record_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "product_family",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("family_code", sa.String(length=128), nullable=False),
        sa.Column("family_name", sa.String(length=256), nullable=False),
        sa.Column("family_type", sa.String(length=64), nullable=False),
        sa.Column("workload_type", sa.String(length=256), nullable=True),
        sa.Column("architecture", sa.String(length=64), nullable=True),
        sa.Column("processor_vendor", sa.String(length=128), nullable=True),
        sa.Column("processor_model_raw", sa.String(length=256), nullable=True),
        sa.Column("generation", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "family_type IN ('ecs_instance_family', 'obs_storage_class')",
            name="product_family_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'preview', 'retired', 'unknown')",
            name="product_family_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown')",
            name="product_family_review_status",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "family_code", name="uq_product_family_code"),
    )
    op.create_index("ix_product_family_evidence_id", "product_family", ["evidence_id"])
    op.create_index("ix_product_family_product_id", "product_family", ["product_id"])

    op.create_table(
        "service_tier",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("tier_code", sa.String(length=128), nullable=False),
        sa.Column("official_name", sa.String(length=256), nullable=False),
        sa.Column("access_pattern", sa.Text(), nullable=True),
        sa.Column("minimum_storage_duration_days", sa.Integer(), nullable=True),
        sa.Column("retrieval_characteristics", sa.Text(), nullable=True),
        sa.Column("availability_design", sa.Text(), nullable=True),
        sa.Column("durability_design", sa.Text(), nullable=True),
        sa.Column("supported_region", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'preview', 'retired', 'unknown')",
            name="service_tier_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown')",
            name="service_tier_review_status",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "tier_code", name="uq_service_tier_product_code"),
    )
    op.create_index("ix_service_tier_evidence_id", "service_tier", ["evidence_id"])
    op.create_index("ix_service_tier_product_id", "service_tier", ["product_id"])

    op.create_table(
        "product_sla",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=False),
        sa.Column("metric_name", sa.String(length=256), nullable=False),
        sa.Column("scope", sa.String(length=256), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalized_percentage", sa.Numeric(18, 12), nullable=True),
        sa.Column("effective_notes", sa.Text(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "review_status IN ('machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown')",
            name="product_sla_review_status",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "record_type",
            "scope",
            "raw_value",
            "evidence_id",
            name="uq_product_sla_evidence_value",
        ),
    )
    op.create_index("ix_product_sla_evidence_id", "product_sla", ["evidence_id"])
    op.create_index("ix_product_sla_product_id", "product_sla", ["product_id"])

    op.create_table(
        "parsing_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_record_id", sa.Integer(), nullable=True),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column("parser_name", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("records_found", sa.Integer(), nullable=False),
        sa.Column("fields_found", sa.Integer(), nullable=False),
        sa.Column("evidence_created", sa.Integer(), nullable=False),
        sa.Column("review_items_created", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'unchanged', 'failed', 'partial', 'skipped')",
            name="parsing_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_record_id"], ["snapshot_record.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_document.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parsing_run_source_id", "parsing_run", ["source_id"])
    op.create_index("ix_parsing_run_snapshot_record_id", "parsing_run", ["snapshot_record_id"])
    op.create_index("ix_parsing_run_source_document_id", "parsing_run", ["source_document_id"])

    op.create_table(
        "parsed_field_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parsing_run_id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_record_id", sa.Integer(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("target_table", sa.String(length=128), nullable=False),
        sa.Column("target_identity", sa.String(length=256), nullable=False),
        sa.Column("field_code", sa.String(length=128), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("raw_unit", sa.String(length=64), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("canonical_unit", sa.String(length=64), nullable=True),
        sa.Column("locator", sa.String(length=512), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("parser_rule", sa.String(length=128), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="parsed_field_confidence"),
        sa.CheckConstraint(
            "review_status IN ('machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown')",
            name="parsed_field_review_status",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parsing_run_id"], ["parsing_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["snapshot_record_id"], ["snapshot_record.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_document.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parsing_run_id",
            "field_code",
            "target_table",
            "target_identity",
            "value_hash",
            name="uq_parsed_field_candidate_identity",
        ),
    )
    op.create_index(
        "ix_parsed_field_candidate_evidence_id", "parsed_field_candidate", ["evidence_id"]
    )
    op.create_index(
        "ix_parsed_field_candidate_parsing_run_id", "parsed_field_candidate", ["parsing_run_id"]
    )
    op.create_index(
        "ix_parsed_field_candidate_snapshot_record_id",
        "parsed_field_candidate",
        ["snapshot_record_id"],
    )
    op.create_index(
        "ix_parsed_field_candidate_source_document_id",
        "parsed_field_candidate",
        ["source_document_id"],
    )

    op.create_table(
        "review_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=True),
        sa.Column("product_code", sa.String(length=128), nullable=True),
        sa.Column("field_code", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("parsing_run_id", sa.Integer(), nullable=True),
        sa.Column("parsed_field_candidate_id", sa.Integer(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            "item_type IN ('low_confidence_field', 'conflicting_official_source', 'manual_review_required', 'unsupported_table', 'quality_issue')",
            name="review_item_type",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="review_item_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'rejected')",
            name="review_item_status",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["parsed_field_candidate_id"], ["parsed_field_candidate.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["parsing_run_id"], ["parsing_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_item_evidence_id", "review_item", ["evidence_id"])
    op.create_index("ix_review_item_field_code", "review_item", ["field_code"])
    op.create_index(
        "ix_review_item_parsed_field_candidate_id", "review_item", ["parsed_field_candidate_id"]
    )
    op.create_index("ix_review_item_parsing_run_id", "review_item", ["parsing_run_id"])
    op.create_index("ix_review_item_product_code", "review_item", ["product_code"])
    op.create_index("ix_review_item_provider_code", "review_item", ["provider_code"])

    op.create_table(
        "data_quality_issue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=False),
        sa.Column("product_code", sa.String(length=128), nullable=True),
        sa.Column("issue_type", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("field_code", sa.String(length=128), nullable=True),
        sa.Column("parsing_run_id", sa.Integer(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="data_quality_issue_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'rejected')",
            name="data_quality_issue_status",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parsing_run_id"], ["parsing_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_quality_issue_evidence_id", "data_quality_issue", ["evidence_id"])
    op.create_index(
        "ix_data_quality_issue_parsing_run_id", "data_quality_issue", ["parsing_run_id"]
    )
    op.create_index("ix_data_quality_issue_product_code", "data_quality_issue", ["product_code"])
    op.create_index("ix_data_quality_issue_provider_code", "data_quality_issue", ["provider_code"])


def downgrade() -> None:
    op.drop_index("ix_data_quality_issue_provider_code", table_name="data_quality_issue")
    op.drop_index("ix_data_quality_issue_product_code", table_name="data_quality_issue")
    op.drop_index("ix_data_quality_issue_parsing_run_id", table_name="data_quality_issue")
    op.drop_index("ix_data_quality_issue_evidence_id", table_name="data_quality_issue")
    op.drop_table("data_quality_issue")
    op.drop_index("ix_review_item_provider_code", table_name="review_item")
    op.drop_index("ix_review_item_product_code", table_name="review_item")
    op.drop_index("ix_review_item_parsing_run_id", table_name="review_item")
    op.drop_index("ix_review_item_parsed_field_candidate_id", table_name="review_item")
    op.drop_index("ix_review_item_field_code", table_name="review_item")
    op.drop_index("ix_review_item_evidence_id", table_name="review_item")
    op.drop_table("review_item")
    op.drop_index(
        "ix_parsed_field_candidate_source_document_id", table_name="parsed_field_candidate"
    )
    op.drop_index(
        "ix_parsed_field_candidate_snapshot_record_id", table_name="parsed_field_candidate"
    )
    op.drop_index("ix_parsed_field_candidate_parsing_run_id", table_name="parsed_field_candidate")
    op.drop_index("ix_parsed_field_candidate_evidence_id", table_name="parsed_field_candidate")
    op.drop_table("parsed_field_candidate")
    op.drop_index("ix_parsing_run_source_document_id", table_name="parsing_run")
    op.drop_index("ix_parsing_run_snapshot_record_id", table_name="parsing_run")
    op.drop_index("ix_parsing_run_source_id", table_name="parsing_run")
    op.drop_table("parsing_run")
    op.drop_index("ix_product_sla_product_id", table_name="product_sla")
    op.drop_index("ix_product_sla_evidence_id", table_name="product_sla")
    op.drop_table("product_sla")
    op.drop_index("ix_service_tier_product_id", table_name="service_tier")
    op.drop_index("ix_service_tier_evidence_id", table_name="service_tier")
    op.drop_table("service_tier")
    op.drop_index("ix_product_family_product_id", table_name="product_family")
    op.drop_index("ix_product_family_evidence_id", table_name="product_family")
    op.drop_table("product_family")
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.drop_constraint(
            "fk_evidence_snapshot_record_id_snapshot_record",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_evidence_snapshot_record_id")
        batch_op.drop_column("parser_rule")
        batch_op.drop_column("content_hash")
        batch_op.drop_column("snapshot_record_id")
        batch_op.drop_column("page_title")
