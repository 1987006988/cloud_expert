from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin
from cloud_expert.database.enums import (
    QualityIssueSeverity,
    ReviewItemStatus,
    ReviewItemType,
    sql_in_values,
)


class ReviewItem(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"item_type IN ({sql_in_values(ReviewItemType.values())})",
            name="review_item_type",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(ReviewItemStatus.values())})",
            name="review_item_status",
        ),
        CheckConstraint(
            f"severity IN ({sql_in_values(QualityIssueSeverity.values())})",
            name="review_item_severity",
        ),
    )

    item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_code: Mapped[str | None] = mapped_column(String(64), index=True)
    product_code: Mapped[str | None] = mapped_column(String(128), index=True)
    field_code: Mapped[str | None] = mapped_column(String(128), index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(Text)
    parsing_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("parsing_run.id", ondelete="SET NULL"),
        index=True,
    )
    parsed_field_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("parsed_field_candidate.id", ondelete="SET NULL"),
        index=True,
    )
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(128))

    parsing_run = relationship("ParsingRun")
    parsed_field_candidate = relationship("ParsedFieldCandidate")
    evidence = relationship("Evidence")


class DataQualityIssue(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"severity IN ({sql_in_values(QualityIssueSeverity.values())})",
            name="data_quality_issue_severity",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(ReviewItemStatus.values())})",
            name="data_quality_issue_status",
        ),
    )

    provider_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_code: Mapped[str | None] = mapped_column(String(128), index=True)
    issue_type: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    field_code: Mapped[str | None] = mapped_column(String(128))
    parsing_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("parsing_run.id", ondelete="SET NULL"),
        index=True,
    )
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    parsing_run = relationship("ParsingRun")
    evidence = relationship("Evidence")


class HumanReviewImportBatch(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (UniqueConstraint("batch_code", name="uq_human_review_import_batch_code"),)

    batch_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    package_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_by: Mapped[str] = mapped_column(String(128), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    total_rows: Mapped[int] = mapped_column(nullable=False, default=0)
    applied_rows: Mapped[int] = mapped_column(nullable=False, default=0)
    rejected_for_reparse_rows: Mapped[int] = mapped_column(nullable=False, default=0)
    deferred_rows: Mapped[int] = mapped_column(nullable=False, default=0)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class HumanReviewDecision(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "review_area",
            "source_row_id",
            name="uq_human_review_decision_source_row",
        ),
    )

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("human_review_import_batch.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    review_area: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_row_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[int | None] = mapped_column(index=True)
    reviewer_decision: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    action_status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    batch: Mapped[HumanReviewImportBatch] = relationship()
