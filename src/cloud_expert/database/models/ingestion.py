from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin
from cloud_expert.database.enums import IngestionRunStatus, IngestionRunType, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.snapshot import SnapshotRecord


class IngestionRun(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"run_type IN ({sql_in_values(IngestionRunType.values())})",
            name="ingestion_run_type",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(IngestionRunStatus.values())})",
            name="ingestion_run_status",
        ),
        CheckConstraint(
            "bytes_downloaded IS NULL OR bytes_downloaded >= 0",
            name="ingestion_run_bytes_non_negative",
        ),
        CheckConstraint("retry_count >= 0", name="ingestion_run_retry_count_non_negative"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ingestion_run_duration_non_negative"
        ),
    )

    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    requested_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2048))
    http_status: Mapped[int | None]
    content_type: Mapped[str | None] = mapped_column(String(128))
    bytes_downloaded: Mapped[int | None] = mapped_column(BigInteger)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    duration_ms: Mapped[int | None]
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshot_record.id", ondelete="SET NULL"),
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    snapshot: Mapped["SnapshotRecord | None"] = relationship()
