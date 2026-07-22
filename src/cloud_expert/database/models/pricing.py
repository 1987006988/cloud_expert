from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import BillingMode, ChargeCategory, DiscountType, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.product import SKU, Product
    from cloud_expert.database.models.provider import Provider
    from cloud_expert.database.models.region import Region
    from cloud_expert.database.models.source import Evidence


class PriceSKU(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __tablename__ = "price_sku"
    __table_args__ = (
        UniqueConstraint("provider_id", "provider_price_code", name="uq_price_sku_provider_code"),
        CheckConstraint(
            f"charge_category IN ({sql_in_values(ChargeCategory.values())})",
            name="price_sku_charge_category",
        ),
        CheckConstraint(
            f"billing_mode IN ({sql_in_values(BillingMode.values())})",
            name="price_sku_billing_mode",
        ),
        CheckConstraint("length(currency) = 3", name="price_sku_currency_len"),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("sku.id", ondelete="RESTRICT"),
        index=True,
    )
    region_id: Mapped[int] = mapped_column(
        ForeignKey("region.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_price_code: Mapped[str] = mapped_column(String(128), nullable=False)
    charge_category: Mapped[str] = mapped_column(String(64), nullable=False)
    billing_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    billing_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    provider: Mapped["Provider"] = relationship()
    product: Mapped["Product"] = relationship()
    sku: Mapped["SKU | None"] = relationship()
    region: Mapped["Region"] = relationship()
    snapshots: Mapped[list["PriceSnapshot"]] = relationship(back_populates="price_sku")


class PriceSnapshot(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="price_snapshot_unit_price_non_negative"),
        CheckConstraint(
            "minimum_quantity IS NULL OR minimum_quantity >= 0",
            name="price_snapshot_min_quantity_non_negative",
        ),
        CheckConstraint(
            "maximum_quantity IS NULL OR maximum_quantity >= 0",
            name="price_snapshot_max_quantity_non_negative",
        ),
        CheckConstraint(
            "maximum_quantity IS NULL OR minimum_quantity IS NULL "
            "OR maximum_quantity >= minimum_quantity",
            name="price_snapshot_quantity_range",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="price_snapshot_effective_range",
        ),
        CheckConstraint(
            f"discount_type IN ({sql_in_values(DiscountType.values())})",
            name="price_snapshot_discount_type",
        ),
    )

    price_sku_id: Mapped[int] = mapped_column(
        ForeignKey("price_sku.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    minimum_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    maximum_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    billing_period: Mapped[str | None] = mapped_column(String(64))
    discount_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DiscountType.UNKNOWN.value,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_payload_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    price_sku: Mapped[PriceSKU] = relationship(back_populates="snapshots")
    evidence: Mapped["Evidence"] = relationship()
