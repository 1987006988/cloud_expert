from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import DataType, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.product import SKU, Product, ProductCategory
    from cloud_expert.database.models.source import Evidence


class SpecificationDefinition(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("code", name="uq_specification_definition_code"),
        CheckConstraint(
            f"data_type IN ({sql_in_values(DataType.values())})",
            name="specification_definition_data_type",
        ),
    )

    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("product_category.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_unit: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(nullable=False, default=False)

    category: Mapped["ProductCategory"] = relationship()


class ProductSpecification(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN numeric_value IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN text_value IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN boolean_value IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="product_specification_exactly_one_value",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="product_specification_valid_range",
        ),
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
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("specification_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    numeric_value: Mapped[float | None] = mapped_column(Numeric(24, 8))
    text_value: Mapped[str | None] = mapped_column(Text)
    boolean_value: Mapped[bool | None]
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    raw_unit: Mapped[str | None] = mapped_column(String(64))
    canonical_value: Mapped[str | None] = mapped_column(String(256))
    canonical_unit: Mapped[str | None] = mapped_column(String(64))
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped["Product"] = relationship()
    sku: Mapped["SKU | None"] = relationship()
    definition: Mapped[SpecificationDefinition] = relationship()
    evidence: Mapped["Evidence"] = relationship()
