from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import (
    AuthorityLevel,
    EvidenceType,
    ReviewStatus,
    SourceType,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.provider import Provider


class SourceDocument(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("url", "content_hash", name="uq_source_document_url_hash"),
        CheckConstraint(
            f"source_type IN ({sql_in_values(SourceType.values())})",
            name="source_document_source_type",
        ),
        CheckConstraint(
            f"authority_level IN ({sql_in_values(AuthorityLevel.values())})",
            name="source_document_authority_level",
        ),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    cloud_partition: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(16))
    authority_level: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    http_status: Mapped[int | None]
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    provider: Mapped["Provider"] = relationship()
    evidence_items: Mapped[list["Evidence"]] = relationship(back_populates="source_document")


class Evidence(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="evidence_confidence_range"),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="evidence_review_status",
        ),
        CheckConstraint(
            f"evidence_type IN ({sql_in_values(EvidenceType.values())})",
            name="evidence_type",
        ),
    )

    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_document.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    section_title: Mapped[str | None] = mapped_column(String(256))
    page_title: Mapped[str | None] = mapped_column(String(256))
    locator: Mapped[str] = mapped_column(String(512), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshot_record.id", ondelete="SET NULL"),
        index=True,
    )
    content_hash: Mapped[str | None] = mapped_column(String(128))
    parser_rule: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float] = mapped_column(nullable=False)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_document: Mapped[SourceDocument] = relationship(back_populates="evidence_items")
