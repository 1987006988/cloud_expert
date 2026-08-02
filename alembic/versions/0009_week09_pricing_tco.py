"""Add week 9 pricing scenario and TCO result models.

Revision ID: 0009_week09_pricing_tco
Revises: 0008_week08_evidence_packages
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_week09_pricing_tco"
down_revision: str | None = "0008_week08_evidence_packages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKET_MODES = "'domestic', 'international'"
SCENARIO_STATUS = "'draft', 'active', 'archived'"
RUN_STATUS = "'succeeded', 'partial', 'failed'"
TAX_STATUS = (
    "'tax_included', 'tax_excluded', 'tax_unknown', 'region_dependent', 'customer_dependent'"
)
COMPLETENESS_STATUS = (
    "'complete', 'partial', 'missing_price', 'estimated_only', "
    "'insufficient_evidence', 'requires_review'"
)
FRESHNESS_STATUS = "'fresh', 'due_soon', 'stale', 'unknown', 'historical'"
COMPARABILITY_STATUS = "'comparable', 'partial', 'not_comparable', 'needs_review'"


def upgrade() -> None:
    op.create_table(
        "pricing_scenario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_code", sa.String(length=160), nullable=False),
        sa.Column("scenario_version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("market_mode", sa.String(length=64), nullable=False),
        sa.Column("billing_period", sa.String(length=64), nullable=False),
        sa.Column("target_currency", sa.String(length=3), nullable=False),
        sa.Column("workload_profile", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"market_mode IN ({MARKET_MODES})", name="pricing_scenario_market_mode"),
        sa.CheckConstraint("length(target_currency) = 3", name="pricing_scenario_currency_len"),
        sa.CheckConstraint(f"status IN ({SCENARIO_STATUS})", name="pricing_scenario_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_code", "scenario_version", name="uq_pricing_scenario_version"
        ),
    )
    op.create_index("ix_pricing_scenario_scenario_code", "pricing_scenario", ["scenario_code"])

    op.create_table(
        "cost_calculation_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("run_code", sa.String(length=160), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("price_snapshot_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider_count", sa.Integer(), nullable=False),
        sa.Column("line_item_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.CheckConstraint("length(currency) = 3", name="cost_calculation_run_currency_len"),
        sa.CheckConstraint(f"status IN ({RUN_STATUS})", name="cost_calculation_run_status"),
        sa.CheckConstraint("provider_count >= 0", name="cost_calculation_run_provider_count"),
        sa.CheckConstraint("line_item_count >= 0", name="cost_calculation_run_line_item_count"),
        sa.CheckConstraint("warning_count >= 0", name="cost_calculation_run_warning_count"),
        sa.CheckConstraint("error_count >= 0", name="cost_calculation_run_error_count"),
        sa.ForeignKeyConstraint(["scenario_id"], ["pricing_scenario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_code", name="uq_cost_calculation_run_code"),
    )
    op.create_index("ix_cost_calculation_run_run_code", "cost_calculation_run", ["run_code"])
    op.create_index("ix_cost_calculation_run_scenario_id", "cost_calculation_run", ["scenario_id"])

    op.create_table(
        "cost_line_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("price_sku_id", sa.Integer(), nullable=True),
        sa.Column("price_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("dimension", sa.String(length=128), nullable=False),
        sa.Column("usage_quantity", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("usage_unit", sa.String(length=64), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("tax_status", sa.String(length=64), nullable=False),
        sa.Column("formula", sa.String(length=512), nullable=True),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column("missing_reason", sa.Text(), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "usage_quantity IS NULL OR usage_quantity >= 0",
            name="cost_line_item_usage_non_negative",
        ),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="cost_line_item_unit_price_non_negative",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0", name="cost_line_item_amount_non_negative"
        ),
        sa.CheckConstraint(f"tax_status IN ({TAX_STATUS})", name="cost_line_item_tax_status"),
        sa.CheckConstraint(
            "length(currency) = 3 OR currency IS NULL", name="cost_line_item_currency"
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_sku_id"], ["price_sku.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_snapshot_id"], ["price_snapshot.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["cost_calculation_run.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in [
        "run_id",
        "provider_id",
        "product_id",
        "price_sku_id",
        "price_snapshot_id",
        "evidence_id",
    ]:
        op.create_index(f"ix_cost_line_item_{column}", "cost_line_item", [column])

    op.create_table(
        "tco_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("tax_amount", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("total", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("billing_period", sa.String(length=64), nullable=False),
        sa.Column("completeness_status", sa.String(length=64), nullable=False),
        sa.Column("freshness_status", sa.String(length=64), nullable=False),
        sa.Column("comparability_status", sa.String(length=64), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("missing_price_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("subtotal IS NULL OR subtotal >= 0", name="tco_result_subtotal"),
        sa.CheckConstraint("tax_amount IS NULL OR tax_amount >= 0", name="tco_result_tax_amount"),
        sa.CheckConstraint("total IS NULL OR total >= 0", name="tco_result_total"),
        sa.CheckConstraint("length(currency) = 3", name="tco_result_currency_len"),
        sa.CheckConstraint("warning_count >= 0", name="tco_result_warning_count"),
        sa.CheckConstraint("missing_price_count >= 0", name="tco_result_missing_price_count"),
        sa.CheckConstraint(
            f"completeness_status IN ({COMPLETENESS_STATUS})",
            name="tco_result_completeness_status",
        ),
        sa.CheckConstraint(
            f"freshness_status IN ({FRESHNESS_STATUS})",
            name="tco_result_freshness_status",
        ),
        sa.CheckConstraint(
            f"comparability_status IN ({COMPARABILITY_STATUS})",
            name="tco_result_comparability_status",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["cost_calculation_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scenario_id"], ["pricing_scenario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "provider_id", "product_id", name="uq_tco_result_run_product"
        ),
    )
    for column in ["run_id", "scenario_id", "provider_id", "product_id"]:
        op.create_index(f"ix_tco_result_{column}", "tco_result", [column])


def downgrade() -> None:
    for column in ["product_id", "provider_id", "scenario_id", "run_id"]:
        op.drop_index(f"ix_tco_result_{column}", table_name="tco_result")
    op.drop_table("tco_result")

    for column in [
        "evidence_id",
        "price_snapshot_id",
        "price_sku_id",
        "product_id",
        "provider_id",
        "run_id",
    ]:
        op.drop_index(f"ix_cost_line_item_{column}", table_name="cost_line_item")
    op.drop_table("cost_line_item")

    op.drop_index("ix_cost_calculation_run_scenario_id", table_name="cost_calculation_run")
    op.drop_index("ix_cost_calculation_run_run_code", table_name="cost_calculation_run")
    op.drop_table("cost_calculation_run")

    op.drop_index("ix_pricing_scenario_scenario_code", table_name="pricing_scenario")
    op.drop_table("pricing_scenario")
