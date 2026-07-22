from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import AvailabilityStatus, MarketMode, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.cloud_partition import CloudPartition
    from cloud_expert.database.models.product import Product
    from cloud_expert.database.models.provider import Provider
    from cloud_expert.database.models.source import Evidence


class Region(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("provider_id", "code", name="uq_region_provider_code"),
        CheckConstraint("length(country_code) = 2", name="region_country_code_len"),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.values())})",
            name="region_market_mode",
        ),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cloud_partition_id: Mapped[int | None] = mapped_column(
        ForeignKey("cloud_partition.id", ondelete="SET NULL"),
        index=True,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    geography: Mapped[str | None] = mapped_column(String(128))
    market_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    provider: Mapped["Provider"] = relationship(back_populates="regions")
    cloud_partition: Mapped["CloudPartition | None"] = relationship()


class AvailabilityZone(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __tablename__ = "availability_zone"
    __table_args__ = (
        UniqueConstraint("provider_id", "zone_code", name="uq_zone_provider_code"),
        UniqueConstraint("region_id", "zone_code", name="uq_zone_region_code"),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.values())})",
            name="availability_zone_market_mode",
        ),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[int] = mapped_column(
        ForeignKey("region.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cloud_partition_id: Mapped[int | None] = mapped_column(
        ForeignKey("cloud_partition.id", ondelete="SET NULL"),
        index=True,
    )
    zone_code: Mapped[str] = mapped_column(String(128), nullable=False)
    zone_name: Mapped[str] = mapped_column(String(256), nullable=False)
    market_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )

    provider: Mapped["Provider"] = relationship()
    region: Mapped[Region] = relationship()
    cloud_partition: Mapped["CloudPartition | None"] = relationship()
    evidence: Mapped["Evidence | None"] = relationship()


class Availability(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "region_id",
            "target_type",
            "target_code",
            name="uq_availability_product_region_target",
        ),
        CheckConstraint(
            f"availability_status IN ({sql_in_values(AvailabilityStatus.values())})",
            name="availability_status",
        ),
        CheckConstraint(
            "availability_status NOT IN ('available', 'preview', 'limited') "
            "OR evidence_id IS NOT NULL",
            name="availability_positive_requires_evidence",
        ),
        CheckConstraint(
            "unavailable_since IS NULL OR available_since IS NULL "
            "OR unavailable_since >= available_since",
            name="availability_time_range",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[int] = mapped_column(
        ForeignKey("region.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cloud_partition_id: Mapped[int | None] = mapped_column(
        ForeignKey("cloud_partition.id", ondelete="SET NULL"),
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, default="product")
    target_code: Mapped[str] = mapped_column(String(256), nullable=False, default="product")
    availability_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AvailabilityStatus.UNKNOWN.value,
    )
    public_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generally_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    available_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unavailable_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )

    product: Mapped["Product"] = relationship()
    region: Mapped[Region] = relationship()
    cloud_partition: Mapped["CloudPartition | None"] = relationship()
    evidence: Mapped["Evidence | None"] = relationship()


class ZoneAvailability(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __tablename__ = "zone_availability"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "availability_zone_id",
            "target_type",
            "target_code",
            name="uq_zone_availability_product_zone_target",
        ),
        CheckConstraint(
            f"availability_status IN ({sql_in_values(AvailabilityStatus.values())})",
            name="zone_availability_status",
        ),
        CheckConstraint(
            "availability_status NOT IN ('available', 'preview', 'limited') "
            "OR evidence_id IS NOT NULL",
            name="zone_availability_positive_requires_evidence",
        ),
        CheckConstraint(
            "unavailable_since IS NULL OR available_since IS NULL "
            "OR unavailable_since >= available_since",
            name="zone_availability_time_range",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    region_id: Mapped[int] = mapped_column(
        ForeignKey("region.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    availability_zone_id: Mapped[int] = mapped_column(
        ForeignKey("availability_zone.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cloud_partition_id: Mapped[int | None] = mapped_column(
        ForeignKey("cloud_partition.id", ondelete="SET NULL"),
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, default="product")
    target_code: Mapped[str] = mapped_column(String(256), nullable=False, default="product")
    availability_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AvailabilityStatus.UNKNOWN.value,
    )
    public_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generally_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    available_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unavailable_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )

    product: Mapped["Product"] = relationship()
    region: Mapped[Region] = relationship()
    availability_zone: Mapped[AvailabilityZone] = relationship()
    cloud_partition: Mapped["CloudPartition | None"] = relationship()
    evidence: Mapped["Evidence | None"] = relationship()
