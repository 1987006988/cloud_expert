"""Add append-only model-review queue overlay and transition audit.

Revision ID: 0014_week14_review_workflow
Revises: 0013_week12_market_context
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0014_week14_review_workflow"
down_revision: str | None = "0013_week12_market_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DATA = sa.JSON().with_variant(JSONB, "postgresql")
STATES = (
    "pending_model_review",
    "blocked_by_deterministic_check",
    "model_review_in_progress",
    "model_approved",
    "model_approved_with_conditions",
    "model_rejected_reparse",
    "model_inconclusive",
    "model_blocked",
    "superseded",
    "expired",
)
STATE_SQL = ", ".join(f"'{state}'" for state in STATES)


def upgrade() -> None:
    op.create_table(
        "model_review_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "precheck_run_id",
            sa.Integer(),
            sa.ForeignKey("model_review_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "precheck_finding_id",
            sa.Integer(),
            sa.ForeignKey("model_review_finding.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("prior_review_status", sa.String(64)),
        sa.Column("review_state", sa.String(64), nullable=False),
        sa.Column("evidence_ids", JSON_DATA, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("precheck_finding_id", name="uq_model_review_assignment_finding"),
        sa.CheckConstraint(f"review_state IN ({STATE_SQL})", name="model_review_assignment_state"),
    )
    op.create_index(
        "ix_model_review_assignment_precheck_run_id", "model_review_assignment", ["precheck_run_id"]
    )
    op.create_index(
        "ix_model_review_assignment_target_type", "model_review_assignment", ["target_type"]
    )
    op.create_index(
        "ix_model_review_assignment_target_id", "model_review_assignment", ["target_id"]
    )
    op.create_table(
        "model_review_audit_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("model_review_assignment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_code", sa.String(160), nullable=False),
        sa.Column("previous_status", sa.String(64)),
        sa.Column("new_status", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(128)),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("affected_records", JSON_DATA, nullable=False),
        sa.Column("downstream_rebuild_required", sa.Boolean(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assignment_id", "event_code", name="uq_model_review_audit_event_code"),
        sa.CheckConstraint(f"new_status IN ({STATE_SQL})", name="model_review_audit_new_state"),
    )
    op.create_index(
        "ix_model_review_audit_event_assignment_id", "model_review_audit_event", ["assignment_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM model_review_assignment")).scalar_one():
        raise RuntimeError("Cannot downgrade nonempty model_review_assignment")
    if bind.execute(sa.text("SELECT COUNT(*) FROM model_review_audit_event")).scalar_one():
        raise RuntimeError("Cannot downgrade nonempty model_review_audit_event")
    op.drop_index(
        "ix_model_review_audit_event_assignment_id", table_name="model_review_audit_event"
    )
    op.drop_table("model_review_audit_event")
    op.drop_index("ix_model_review_assignment_target_id", table_name="model_review_assignment")
    op.drop_index("ix_model_review_assignment_target_type", table_name="model_review_assignment")
    op.drop_index(
        "ix_model_review_assignment_precheck_run_id", table_name="model_review_assignment"
    )
    op.drop_table("model_review_assignment")
