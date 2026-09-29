from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin
from cloud_expert.database.enums import (
    MarketCompatibilityStatus,
    MarketMode,
    TaxStatus,
    sql_in_values,
)

JSON_SCOPE = JSON().with_variant(JSONB, "postgresql")


class MarketContext(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("context_code", name="uq_market_context_code"),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.values())})",
            name="market_context_mode",
        ),
        CheckConstraint(
            f"tax_context IN ({sql_in_values(TaxStatus.values())})",
            name="market_context_tax",
        ),
        CheckConstraint(
            "country_code IS NULL OR length(country_code) = 2",
            name="market_context_country_len",
        ),
        CheckConstraint(
            "target_currency IS NULL OR length(target_currency) = 3",
            name="market_context_currency_len",
        ),
    )

    context_code: Mapped[str] = mapped_column(String(160), nullable=False)
    market_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    geography_code: Mapped[str | None] = mapped_column(String(64))
    preferred_region_codes: Mapped[list[str]] = mapped_column(JSON_SCOPE, nullable=False)
    provider_partition_codes: Mapped[list[str]] = mapped_column(JSON_SCOPE, nullable=False)
    target_currency: Mapped[str | None] = mapped_column(String(3))
    tax_context: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    regulatory_context: Mapped[dict[str, Any] | None] = mapped_column(JSON_SCOPE)
    data_residency_context: Mapped[dict[str, Any] | None] = mapped_column(JSON_SCOPE)
    pricing_market: Mapped[str | None] = mapped_column(String(64))
    source_scope: Mapped[str | None] = mapped_column(String(64))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketCompatibilityAssessment(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "left_fingerprint",
            "right_fingerprint",
            "rule_version",
            name="uq_market_compatibility_identity",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(MarketCompatibilityStatus.values())})",
            name="market_compatibility_status",
        ),
    )

    left_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    right_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON_SCOPE, nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
