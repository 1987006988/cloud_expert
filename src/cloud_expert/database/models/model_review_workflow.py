from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin

JSON_DATA = JSON().with_variant(JSONB, "postgresql")
REVIEW_STATES = (
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
STATE_SQL = ", ".join(f"'{state}'" for state in REVIEW_STATES)


class ModelReviewAssignment(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("precheck_finding_id", name="uq_model_review_assignment_finding"),
        CheckConstraint(f"review_state IN ({STATE_SQL})", name="model_review_assignment_state"),
    )

    precheck_run_id: Mapped[int] = mapped_column(
        ForeignKey("model_review_run.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    precheck_finding_id: Mapped[int] = mapped_column(
        ForeignKey("model_review_finding.id", ondelete="RESTRICT"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_review_status: Mapped[str | None] = mapped_column(String(64))
    review_state: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ids: Mapped[list[int]] = mapped_column(JSON_DATA, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    precheck_run = relationship("ModelReviewRun")
    precheck_finding = relationship("ModelReviewFinding")


class ModelReviewAuditEvent(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(f"new_status IN ({STATE_SQL})", name="model_review_audit_new_state"),
        UniqueConstraint("assignment_id", "event_code", name="uq_model_review_audit_event_code"),
    )

    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("model_review_assignment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_code: Mapped[str] = mapped_column(String(160), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(64))
    new_status: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    affected_records: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DATA, nullable=False)
    downstream_rebuild_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    assignment = relationship("ModelReviewAssignment")
