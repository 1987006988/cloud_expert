from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin
from cloud_expert.database.enums import (
    ComparabilityStatus,
    CostCalculationRunStatus,
    FreshnessStatus,
    MarketMode,
    PricingScenarioStatus,
    TaxStatus,
    TCOCompletenessStatus,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
    from cloud_expert.database.models.product import Product
    from cloud_expert.database.models.provider import Provider
    from cloud_expert.database.models.source import Evidence


class PricingScenario(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("scenario_code", "scenario_version", name="uq_pricing_scenario_version"),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.fact_values())})",
            name="pricing_scenario_market_mode",
        ),
        CheckConstraint("length(target_currency) = 3", name="pricing_scenario_currency_len"),
        CheckConstraint(
            f"status IN ({sql_in_values(PricingScenarioStatus.values())})",
            name="pricing_scenario_status",
        ),
    )

    scenario_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    scenario_version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    market_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(64), nullable=False)
    target_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    workload_profile: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=PricingScenarioStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    runs: Mapped[list["CostCalculationRun"]] = relationship(back_populates="scenario")


class CostCalculationRun(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("run_code", name="uq_cost_calculation_run_code"),
        CheckConstraint("length(currency) = 3", name="cost_calculation_run_currency_len"),
        CheckConstraint(
            f"status IN ({sql_in_values(CostCalculationRunStatus.values())})",
            name="cost_calculation_run_status",
        ),
        CheckConstraint("provider_count >= 0", name="cost_calculation_run_provider_count"),
        CheckConstraint("line_item_count >= 0", name="cost_calculation_run_line_item_count"),
        CheckConstraint("warning_count >= 0", name="cost_calculation_run_warning_count"),
        CheckConstraint("error_count >= 0", name="cost_calculation_run_error_count"),
    )

    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("pricing_scenario.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    run_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    price_snapshot_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    scenario: Mapped[PricingScenario] = relationship(back_populates="runs")
    line_items: Mapped[list["CostLineItem"]] = relationship(back_populates="run")
    results: Mapped[list["TCOResult"]] = relationship(back_populates="run")


class CostLineItem(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            "usage_quantity IS NULL OR usage_quantity >= 0",
            name="cost_line_item_usage_non_negative",
        ),
        CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="cost_line_item_unit_price_non_negative",
        ),
        CheckConstraint("amount IS NULL OR amount >= 0", name="cost_line_item_amount_non_negative"),
        CheckConstraint(
            f"tax_status IN ({sql_in_values(TaxStatus.values())})",
            name="cost_line_item_tax_status",
        ),
        CheckConstraint("length(currency) = 3 OR currency IS NULL", name="cost_line_item_currency"),
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("cost_calculation_run.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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
    price_sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_sku.id", ondelete="RESTRICT"),
        index=True,
    )
    price_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_snapshot.id", ondelete="RESTRICT"),
        index=True,
    )
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(128), nullable=False)
    usage_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    usage_unit: Mapped[str | None] = mapped_column(String(64))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    currency: Mapped[str | None] = mapped_column(String(3))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    tax_status: Mapped[str] = mapped_column(String(64), nullable=False)
    formula: Mapped[str | None] = mapped_column(String(512))
    assumptions: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    missing_reason: Mapped[str | None] = mapped_column(Text)
    warning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    run: Mapped[CostCalculationRun] = relationship(back_populates="line_items")
    provider: Mapped["Provider"] = relationship()
    product: Mapped["Product"] = relationship()
    price_sku: Mapped["PriceSKU | None"] = relationship()
    price_snapshot: Mapped["PriceSnapshot | None"] = relationship()
    evidence: Mapped["Evidence | None"] = relationship()


class TCOResult(IDMixin, TableNameMixin, ReprMixin, Base):
    __tablename__ = "tco_result"
    __table_args__ = (
        UniqueConstraint("run_id", "provider_id", "product_id", name="uq_tco_result_run_product"),
        CheckConstraint("subtotal IS NULL OR subtotal >= 0", name="tco_result_subtotal"),
        CheckConstraint("tax_amount IS NULL OR tax_amount >= 0", name="tco_result_tax_amount"),
        CheckConstraint("total IS NULL OR total >= 0", name="tco_result_total"),
        CheckConstraint("length(currency) = 3", name="tco_result_currency_len"),
        CheckConstraint("warning_count >= 0", name="tco_result_warning_count"),
        CheckConstraint("missing_price_count >= 0", name="tco_result_missing_price_count"),
        CheckConstraint(
            f"completeness_status IN ({sql_in_values(TCOCompletenessStatus.values())})",
            name="tco_result_completeness_status",
        ),
        CheckConstraint(
            f"freshness_status IN ({sql_in_values(FreshnessStatus.values())})",
            name="tco_result_freshness_status",
        ),
        CheckConstraint(
            f"comparability_status IN ({sql_in_values(ComparabilityStatus.values())})",
            name="tco_result_comparability_status",
        ),
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("cost_calculation_run.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("pricing_scenario.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    total: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(64), nullable=False)
    completeness_status: Mapped[str] = mapped_column(String(64), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(64), nullable=False)
    comparability_status: Mapped[str] = mapped_column(String(64), nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_price_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    run: Mapped[CostCalculationRun] = relationship(back_populates="results")
    scenario: Mapped[PricingScenario] = relationship()
    provider: Mapped["Provider"] = relationship()
    product: Mapped["Product"] = relationship()
