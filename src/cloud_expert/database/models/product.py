from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
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
    AliasType,
    MarketMode,
    ProductStatus,
    SKUStatus,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.provider import Provider


class ProductCategory(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (UniqueConstraint("code", name="uq_product_category_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_category.id", ondelete="SET NULL"),
    )
    description: Mapped[str | None] = mapped_column(Text)

    parent: Mapped["ProductCategory | None"] = relationship(
        remote_side="ProductCategory.id",
        back_populates="children",
    )
    children: Mapped[list["ProductCategory"]] = relationship(back_populates="parent")
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("provider_id", "code", name="uq_product_provider_code"),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.values())})",
            name="product_market_mode",
        ),
        CheckConstraint(
            f"product_status IN ({sql_in_values(ProductStatus.values())})",
            name="product_status",
        ),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("product_category.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    market_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    official_name: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    product_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProductStatus.UNKNOWN.value,
    )
    official_url: Mapped[str | None] = mapped_column(String(512))
    documentation_url: Mapped[str | None] = mapped_column(String(512))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    provider: Mapped["Provider"] = relationship(back_populates="products")
    category: Mapped[ProductCategory] = relationship(back_populates="products")
    aliases: Mapped[list["ProductAlias"]] = relationship(back_populates="product")
    skus: Mapped[list["SKU"]] = relationship(back_populates="product")


class ProductAlias(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "alias",
            "alias_type",
            "language",
            name="uq_product_alias_identity",
        ),
        CheckConstraint(
            f"alias_type IN ({sql_in_values(AliasType.values())})",
            name="product_alias_type",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(256), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product: Mapped[Product] = relationship(back_populates="aliases")


class SKU(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __tablename__ = "sku"
    __table_args__ = (
        UniqueConstraint("product_id", "provider_sku_code", name="uq_sku_product_provider_code"),
        CheckConstraint(
            f"status IN ({sql_in_values(SKUStatus.values())})",
            name="sku_status",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_sku_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    sku_family: Mapped[str | None] = mapped_column(String(128))
    architecture: Mapped[str | None] = mapped_column(String(64))
    operating_system: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SKUStatus.UNKNOWN.value)

    product: Mapped[Product] = relationship(back_populates="skus")
