"""Add explicit market context and compatibility audit tables.

Revision ID: 0013_week12_market_context
Revises: 0012_week11_model_review_audit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0013_week12_market_context"
down_revision: str | None = "0012_week11_model_review_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_SCOPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "market_context",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("context_code", sa.String(160), nullable=False),
        sa.Column("market_mode", sa.String(32), nullable=False),
        sa.Column("country_code", sa.String(2)),
        sa.Column("geography_code", sa.String(64)),
        sa.Column("preferred_region_codes", JSON_SCOPE, nullable=False),
        sa.Column("provider_partition_codes", JSON_SCOPE, nullable=False),
        sa.Column("target_currency", sa.String(3)),
        sa.Column("tax_context", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16)),
        sa.Column("regulatory_context", JSON_SCOPE),
        sa.Column("data_residency_context", JSON_SCOPE),
        sa.Column("pricing_market", sa.String(64)),
        sa.Column("source_scope", sa.String(64)),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("context_code", name="uq_market_context_code"),
        sa.CheckConstraint(
            "market_mode IN ('domestic', 'international', 'cross_market_analysis', 'unknown')",
            name="market_context_mode",
        ),
        sa.CheckConstraint(
            "tax_context IN ('tax_included', 'tax_excluded', 'tax_unknown', "
            "'region_dependent', 'customer_dependent')",
            name="market_context_tax",
        ),
        sa.CheckConstraint(
            "country_code IS NULL OR length(country_code) = 2", name="market_context_country_len"
        ),
        sa.CheckConstraint(
            "target_currency IS NULL OR length(target_currency) = 3",
            name="market_context_currency_len",
        ),
    )
    op.create_table(
        "market_compatibility_assessment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("left_fingerprint", sa.String(64), nullable=False),
        sa.Column("right_fingerprint", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reasons", JSON_SCOPE, nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "left_fingerprint",
            "right_fingerprint",
            "rule_version",
            name="uq_market_compatibility_identity",
        ),
        sa.CheckConstraint(
            "status IN ('compatible', 'compatible_with_conditions', 'cross_market', "
            "'incompatible', 'unknown', 'requires_review')",
            name="market_compatibility_status",
        ),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM market_context")).scalar_one():
        raise RuntimeError("Cannot downgrade nonempty market_context")
    if (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM market_compatibility_assessment"))
        .scalar_one()
    ):
        raise RuntimeError("Cannot downgrade nonempty market_compatibility_assessment")
    op.drop_table("market_compatibility_assessment")
    op.drop_table("market_context")
