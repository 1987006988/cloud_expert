from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import ClaimType, MarketMode, ReviewStatus, sql_in_values

if TYPE_CHECKING:
    from cloud_expert.database.models.product import Product
    from cloud_expert.database.models.source import Evidence


class CompetitiveClaim(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.values())})",
            name="competitive_claim_market_mode",
        ),
        CheckConstraint(
            f"claim_type IN ({sql_in_values(ClaimType.values())})",
            name="competitive_claim_type",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="competitive_claim_review_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="competitive_claim_confidence_range",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="competitive_claim_valid_range",
        ),
    )

    market_mode: Mapped[str] = mapped_column(String(32), nullable=False)
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
    scenario_code: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    customer_value: Mapped[str | None] = mapped_column(Text)
    applicable_conditions: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_product: Mapped["Product"] = relationship(foreign_keys=[source_product_id])
    target_product: Mapped["Product"] = relationship(foreign_keys=[target_product_id])
    evidence: Mapped["Evidence"] = relationship()
