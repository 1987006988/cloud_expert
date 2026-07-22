from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin
from cloud_expert.database.enums import ChangeStatus, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.source import SourceDocument


class SnapshotRecord(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_snapshot_record_source_hash"),
        CheckConstraint(
            f"change_status IN ({sql_in_values(ChangeStatus.values())})",
            name="snapshot_record_change_status",
        ),
        CheckConstraint("content_length_bytes >= 0", name="snapshot_record_length_non_negative"),
    )

    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_document.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_hash: Mapped[str | None] = mapped_column(String(64))
    normalization_version: Mapped[str | None] = mapped_column(String(32))
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    manifest_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content_length_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshot_record.id", ondelete="SET NULL"),
        index=True,
    )
    change_status: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    source_document: Mapped["SourceDocument"] = relationship()
    previous_snapshot: Mapped["SnapshotRecord | None"] = relationship(
        remote_side="SnapshotRecord.id"
    )
