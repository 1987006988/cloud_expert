from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import MarketMode, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.provider import Provider


class CloudPartition(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "partition_code",
            name="uq_cloud_partition_provider_code",
        ),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.fact_values())})",
            name="cloud_partition_market_mode",
        ),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    partition_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    partition_name: Mapped[str] = mapped_column(String(128), nullable=False)
    market_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    geography_scope: Mapped[str | None] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    provider: Mapped["Provider"] = relationship()
