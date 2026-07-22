"""Add ingestion run and snapshot records.

Revision ID: 0002_ingestion_snapshots
Revises: 0001_initial_product_data_model
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_ingestion_snapshots"
down_revision: str | None = "0001_initial_product_data_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snapshot_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("normalized_hash", sa.String(length=64), nullable=True),
        sa.Column("normalization_version", sa.String(length=32), nullable=True),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("manifest_path", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("content_length_bytes", sa.BigInteger(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("change_status", sa.String(length=64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "change_status IN ('first_seen', 'unchanged', 'content_changed', 'metadata_changed', 'redirect_changed', 'content_type_changed', 'unavailable', 'restored', 'unknown')",
            name="ck_snapshot_record_snapshot_record_change_status",
        ),
        sa.CheckConstraint(
            "content_length_bytes >= 0",
            name="ck_snapshot_record_snapshot_record_length_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["previous_snapshot_id"],
            ["snapshot_record.id"],
            ondelete="SET NULL",
            name="fk_snapshot_record_previous_snapshot_id_snapshot_record",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
            ondelete="RESTRICT",
            name="fk_snapshot_record_source_document_id_source_document",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_snapshot_record"),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_snapshot_record_source_hash"),
    )
    op.create_index("ix_snapshot_record_content_hash", "snapshot_record", ["content_hash"])
    op.create_index(
        "ix_snapshot_record_previous_snapshot_id", "snapshot_record", ["previous_snapshot_id"]
    )
    op.create_index(
        "ix_snapshot_record_source_document_id", "snapshot_record", ["source_document_id"]
    )
    op.create_index("ix_snapshot_record_source_id", "snapshot_record", ["source_id"])

    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("bytes_downloaded", sa.BigInteger(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "run_type IN ('manual', 'scheduled', 'dry_run', 'validation')",
            name="ck_ingestion_run_ingestion_run_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'unchanged', 'failed', 'skipped', 'blocked')",
            name="ck_ingestion_run_ingestion_run_status",
        ),
        sa.CheckConstraint(
            "bytes_downloaded IS NULL OR bytes_downloaded >= 0",
            name="ck_ingestion_run_ingestion_run_bytes_non_negative",
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name="ck_ingestion_run_ingestion_run_retry_count_non_negative",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ingestion_run_ingestion_run_duration_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshot_record.id"],
            ondelete="SET NULL",
            name="fk_ingestion_run_snapshot_id_snapshot_record",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_run"),
    )
    op.create_index("ix_ingestion_run_error_code", "ingestion_run", ["error_code"])
    op.create_index("ix_ingestion_run_snapshot_id", "ingestion_run", ["snapshot_id"])
    op.create_index("ix_ingestion_run_source_id", "ingestion_run", ["source_id"])
    op.create_index("ix_ingestion_run_status", "ingestion_run", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_run_status", table_name="ingestion_run")
    op.drop_index("ix_ingestion_run_source_id", table_name="ingestion_run")
    op.drop_index("ix_ingestion_run_snapshot_id", table_name="ingestion_run")
    op.drop_index("ix_ingestion_run_error_code", table_name="ingestion_run")
    op.drop_table("ingestion_run")
    op.drop_index("ix_snapshot_record_source_id", table_name="snapshot_record")
    op.drop_index("ix_snapshot_record_source_document_id", table_name="snapshot_record")
    op.drop_index("ix_snapshot_record_previous_snapshot_id", table_name="snapshot_record")
    op.drop_index("ix_snapshot_record_content_hash", table_name="snapshot_record")
    op.drop_table("snapshot_record")
