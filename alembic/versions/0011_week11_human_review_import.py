"""Add week 11 human review import audit tables.

Revision ID: 0011_week11_human_review_import
Revises: 0010_week10_decision_engine
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_week11_human_review_import"
down_revision: str | None = "0010_week10_decision_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "human_review_import_batch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_code", sa.String(length=160), nullable=False),
        sa.Column("package_path", sa.String(length=1024), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_by", sa.String(length=128), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("applied_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_for_reparse_rows", sa.Integer(), nullable=False),
        sa.Column("deferred_rows", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_code", name="uq_human_review_import_batch_code"),
    )
    op.create_index(
        "ix_human_review_import_batch_batch_code",
        "human_review_import_batch",
        ["batch_code"],
    )

    op.create_table(
        "human_review_decision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("review_area", sa.String(length=128), nullable=False),
        sa.Column("source_row_id", sa.String(length=128), nullable=False),
        sa.Column("target_table", sa.String(length=128), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_decision", sa.String(length=64), nullable=False),
        sa.Column("reviewer", sa.String(length=128), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("action_status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["human_review_import_batch.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "review_area",
            "source_row_id",
            name="uq_human_review_decision_source_row",
        ),
    )
    op.create_index("ix_human_review_decision_batch_id", "human_review_decision", ["batch_id"])
    op.create_index(
        "ix_human_review_decision_review_area",
        "human_review_decision",
        ["review_area"],
    )
    op.create_index(
        "ix_human_review_decision_source_row_id",
        "human_review_decision",
        ["source_row_id"],
    )
    op.create_index(
        "ix_human_review_decision_target_id",
        "human_review_decision",
        ["target_id"],
    )
    op.create_index(
        "ix_human_review_decision_reviewer_decision",
        "human_review_decision",
        ["reviewer_decision"],
    )


def downgrade() -> None:
    op.drop_index("ix_human_review_decision_reviewer_decision", table_name="human_review_decision")
    op.drop_index("ix_human_review_decision_target_id", table_name="human_review_decision")
    op.drop_index("ix_human_review_decision_source_row_id", table_name="human_review_decision")
    op.drop_index("ix_human_review_decision_review_area", table_name="human_review_decision")
    op.drop_index("ix_human_review_decision_batch_id", table_name="human_review_decision")
    op.drop_table("human_review_decision")
    op.drop_index(
        "ix_human_review_import_batch_batch_code",
        table_name="human_review_import_batch",
    )
    op.drop_table("human_review_import_batch")
