"""Add separate model-review audit records.

Revision ID: 0012_week11_model_review_audit
Revises: 0011_week11_human_review_import
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_week11_model_review_audit"
down_revision: str | None = "0011_week11_human_review_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_review_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_code", sa.String(160), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("reviewer_model", sa.String(128), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_code", name="uq_model_review_run_code"),
    )
    op.create_index("ix_model_review_run_run_code", "model_review_run", ["run_code"])
    op.create_table(
        "model_review_finding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("model_review_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "run_id", "subject_type", "subject_id", name="uq_model_review_finding_subject"
        ),
    )
    for column in ("run_id", "subject_type", "subject_id", "verdict"):
        op.create_index(f"ix_model_review_finding_{column}", "model_review_finding", [column])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM model_review_run")).scalar_one():
        raise RuntimeError("Cannot downgrade model review audit with recorded runs")
    for column in ("verdict", "subject_id", "subject_type", "run_id"):
        op.drop_index(f"ix_model_review_finding_{column}", table_name="model_review_finding")
    op.drop_table("model_review_finding")
    op.drop_index("ix_model_review_run_run_code", table_name="model_review_run")
    op.drop_table("model_review_run")
