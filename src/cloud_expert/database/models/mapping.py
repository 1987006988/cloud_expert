from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import MappingLevel, MappingStatus, ReviewStatus, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.product import SKU, Product
    from cloud_expert.database.models.source import Evidence


class ProductMapping(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"mapping_level IN ({sql_in_values(MappingLevel.values())})",
            name="product_mapping_level",
        ),
        CheckConstraint(
            f"mapping_status IN ({sql_in_values(MappingStatus.values())})",
            name="product_mapping_status",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="product_mapping_review_status",
        ),
        CheckConstraint(
            "source_product_id <> target_product_id",
            name="product_mapping_not_self_product",
        ),
    )

    source_product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("sku.id", ondelete="RESTRICT"),
        index=True,
    )
    target_sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("sku.id", ondelete="RESTRICT"),
        index=True,
    )
    mapping_level: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_status: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_code: Mapped[str] = mapped_column(String(128), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ReviewStatus.PENDING_REVIEW.value,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_product: Mapped["Product"] = relationship(foreign_keys=[source_product_id])
    target_product: Mapped["Product"] = relationship(foreign_keys=[target_product_id])
    source_sku: Mapped["SKU | None"] = relationship(foreign_keys=[source_sku_id])
    target_sku: Mapped["SKU | None"] = relationship(foreign_keys=[target_sku_id])
    evidence: Mapped["Evidence | None"] = relationship()
