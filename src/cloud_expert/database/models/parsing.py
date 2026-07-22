from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin
from cloud_expert.database.enums import ParserRunStatus, ReviewStatus, sql_in_values


class ParsingRun(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"status IN ({sql_in_values(ParserRunStatus.values())})",
            name="parsing_run_status",
        ),
    )

    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    snapshot_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshot_record.id", ondelete="SET NULL"),
        index=True,
    )
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_document.id", ondelete="SET NULL"),
        index=True,
    )
    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    records_found: Mapped[int] = mapped_column(nullable=False, default=0)
    fields_found: Mapped[int] = mapped_column(nullable=False, default=0)
    evidence_created: Mapped[int] = mapped_column(nullable=False, default=0)
    review_items_created: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    snapshot_record = relationship("SnapshotRecord")
    source_document = relationship("SourceDocument")


class ParsedFieldCandidate(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "parsing_run_id",
            "field_code",
            "target_table",
            "target_identity",
            "value_hash",
            name="uq_parsed_field_candidate_identity",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="parsed_field_confidence"),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="parsed_field_review_status",
        ),
    )

    parsing_run_id: Mapped[int] = mapped_column(
        ForeignKey("parsing_run.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_document.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    snapshot_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshot_record.id", ondelete="SET NULL"),
        index=True,
    )
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )
    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    target_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    field_code: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text)
    raw_unit: Mapped[str | None] = mapped_column(String(64))
    normalized_value: Mapped[str | None] = mapped_column(Text)
    canonical_unit: Mapped[str | None] = mapped_column(String(64))
    locator: Mapped[str] = mapped_column(String(512), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_rule: Mapped[str] = mapped_column(String(128), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    parsing_run: Mapped[ParsingRun] = relationship()
    source_document = relationship("SourceDocument")
    snapshot_record = relationship("SnapshotRecord")
    evidence = relationship("Evidence")
