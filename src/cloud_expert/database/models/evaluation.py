from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import EvaluationCaseType, MarketMode, sql_in_values


class SalesScenario(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("code", name="uq_sales_scenario_code"),
        CheckConstraint(
            f"market_mode IN ({sql_in_values(MarketMode.fact_values())})",
            name="sales_scenario_market_mode",
        ),
        CheckConstraint(
            "country_code IS NULL OR length(country_code) = 2", name="sales_country_len"
        ),
    )

    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    market_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128))
    country_code: Mapped[str | None] = mapped_column(String(2))
    description: Mapped[str | None] = mapped_column(Text)
    default_weights_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class EvaluationCase(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("case_code", name="uq_evaluation_case_code"),
        CheckConstraint(
            f"case_type IN ({sql_in_values(EvaluationCaseType.values())})",
            name="evaluation_case_type",
        ),
    )

    case_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expected_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    expected_sources: Mapped[list[str] | None] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
