from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
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
from cloud_expert.database.enums import (
    ProductFamilyType,
    ReviewStatus,
    SKUStatus,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.product import Product
    from cloud_expert.database.models.source import Evidence


class ProductFamily(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("product_id", "family_code", name="uq_product_family_code"),
        CheckConstraint(
            f"family_type IN ({sql_in_values(ProductFamilyType.values())})",
            name="product_family_type",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(SKUStatus.values())})",
            name="product_family_status",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="product_family_review_status",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    family_code: Mapped[str] = mapped_column(String(128), nullable=False)
    family_name: Mapped[str] = mapped_column(String(256), nullable=False)
    family_type: Mapped[str] = mapped_column(String(64), nullable=False)
    workload_type: Mapped[str | None] = mapped_column(String(256))
    architecture: Mapped[str | None] = mapped_column(String(64))
    processor_vendor: Mapped[str | None] = mapped_column(String(128))
    processor_model_raw: Mapped[str | None] = mapped_column(String(256))
    generation: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SKUStatus.UNKNOWN.value)
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ReviewStatus.PENDING_REVIEW.value,
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    product: Mapped["Product"] = relationship()
    evidence: Mapped["Evidence | None"] = relationship()


class ServiceTier(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("product_id", "tier_code", name="uq_service_tier_product_code"),
        CheckConstraint(
            f"status IN ({sql_in_values(SKUStatus.values())})",
            name="service_tier_status",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="service_tier_review_status",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    tier_code: Mapped[str] = mapped_column(String(128), nullable=False)
    official_name: Mapped[str] = mapped_column(String(256), nullable=False)
    access_pattern: Mapped[str | None] = mapped_column(Text)
    minimum_storage_duration_days: Mapped[int | None]
    retrieval_characteristics: Mapped[str | None] = mapped_column(Text)
    availability_design: Mapped[str | None] = mapped_column(Text)
    durability_design: Mapped[str | None] = mapped_column(Text)
    supported_region: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SKUStatus.UNKNOWN.value)
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ReviewStatus.PENDING_REVIEW.value,
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    product: Mapped["Product"] = relationship()
    evidence: Mapped["Evidence | None"] = relationship()


class ProductSLA(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __tablename__ = "product_sla"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "record_type",
            "scope",
            "raw_value",
            "evidence_id",
            name="uq_product_sla_evidence_value",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="product_sla_review_status",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(256), nullable=False)
    scope: Mapped[str] = mapped_column(String(256), nullable=False, default="product")
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_percentage: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    effective_notes: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ReviewStatus.PENDING_REVIEW.value,
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped["Product"] = relationship()
    evidence: Mapped["Evidence"] = relationship()
