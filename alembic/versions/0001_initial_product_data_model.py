"""Initial product data model.

Revision ID: 0001_initial_product_data_model
Revises:
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial_product_data_model"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.create_table(
        "provider",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("official_website", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_provider"),
        sa.UniqueConstraint("code", name="uq_provider_code"),
    )
    op.create_index("ix_provider_code", "provider", ["code"])

    op.create_table(
        "product_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["product_category.id"],
            ondelete="SET NULL",
            name="fk_product_category_parent_id_product_category",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_category"),
        sa.UniqueConstraint("code", name="uq_product_category_code"),
    )
    op.create_index("ix_product_category_code", "product_category", ["code"])

    op.create_table(
        "product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("market_mode", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("official_name", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_status", sa.String(length=32), nullable=False),
        sa.Column("official_url", sa.String(length=512), nullable=True),
        sa.Column("documentation_url", sa.String(length=512), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "market_mode IN ('domestic', 'international')", name="ck_product_product_market_mode"
        ),
        sa.CheckConstraint(
            "product_status IN ('active', 'preview', 'retired', 'unknown')",
            name="ck_product_product_status",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["product_category.id"],
            ondelete="RESTRICT",
            name="fk_product_category_id_product_category",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
            ondelete="RESTRICT",
            name="fk_product_provider_id_provider",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product"),
        sa.UniqueConstraint("provider_id", "code", name="uq_product_provider_code"),
    )
    op.create_index("ix_product_category_id", "product", ["category_id"])
    op.create_index("ix_product_provider_id", "product", ["provider_id"])

    op.create_table(
        "product_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=256), nullable=False),
        sa.Column("alias_type", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("is_official", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "alias_type IN ('chinese_name', 'english_name', 'abbreviation', 'historical_name', 'sales_name', 'other')",
            name="ck_product_alias_product_alias_type",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_product_alias_product_id_product",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_alias"),
        sa.UniqueConstraint(
            "product_id", "alias", "alias_type", "language", name="uq_product_alias_identity"
        ),
    )
    op.create_index("ix_product_alias_product_id", "product_alias", ["product_id"])

    op.create_table(
        "sku",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("provider_sku_code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("sku_family", sa.String(length=128), nullable=True),
        sa.Column("architecture", sa.String(length=64), nullable=True),
        sa.Column("operating_system", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'preview', 'retired', 'unknown')", name="ck_sku_sku_status"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"], ondelete="RESTRICT", name="fk_sku_product_id_product"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sku"),
        sa.UniqueConstraint("product_id", "provider_sku_code", name="uq_sku_product_provider_code"),
    )
    op.create_index("ix_sku_product_id", "sku", ["product_id"])

    op.create_table(
        "region",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("geography", sa.String(length=128), nullable=True),
        sa.Column("market_mode", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("length(country_code) = 2", name="ck_region_region_country_code_len"),
        sa.CheckConstraint(
            "market_mode IN ('domestic', 'international')", name="ck_region_region_market_mode"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
            ondelete="RESTRICT",
            name="fk_region_provider_id_provider",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_region"),
        sa.UniqueConstraint("provider_id", "code", name="uq_region_provider_code"),
    )
    op.create_index("ix_region_provider_id", "region", ["provider_id"])

    op.create_table(
        "source_document",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("authority_level", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_type IN ('product_page', 'documentation', 'specification', 'pricing', 'sla', 'region_availability', 'release_note', 'compliance', 'api_response', 'internal_review')",
            name="ck_source_document_source_document_source_type",
        ),
        sa.CheckConstraint(
            "authority_level IN ('official_primary', 'official_secondary', 'partner', 'third_party', 'internal', 'unknown')",
            name="ck_source_document_source_document_authority_level",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
            ondelete="RESTRICT",
            name="fk_source_document_provider_id_provider",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_document"),
        sa.UniqueConstraint("url", "content_hash", name="uq_source_document_url_hash"),
    )
    op.create_index("ix_source_document_provider_id", "source_document", ["provider_id"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(length=256), nullable=True),
        sa.Column("locator", sa.String(length=512), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_evidence_evidence_confidence_range"
        ),
        sa.CheckConstraint(
            "review_status IN ('machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown')",
            name="ck_evidence_evidence_review_status",
        ),
        sa.CheckConstraint(
            "evidence_type IN ('html_section', 'pdf_page', 'json_path', 'api_field', 'human_note', 'unknown')",
            name="ck_evidence_evidence_type",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
            ondelete="RESTRICT",
            name="fk_evidence_source_document_id_source_document",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
    )
    op.create_index("ix_evidence_source_document_id", "evidence", ["source_document_id"])

    op.create_table(
        "availability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("availability_status", sa.String(length=32), nullable=False),
        sa.Column("public_preview", sa.Boolean(), nullable=False),
        sa.Column("generally_available", sa.Boolean(), nullable=False),
        sa.Column("available_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unavailable_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "availability_status IN ('available', 'preview', 'limited', 'unavailable', 'unknown', 'retired')",
            name="ck_availability_availability_status",
        ),
        sa.CheckConstraint(
            "availability_status NOT IN ('available', 'preview', 'limited') OR evidence_id IS NOT NULL",
            name="ck_availability_availability_positive_requires_evidence",
        ),
        sa.CheckConstraint(
            "unavailable_since IS NULL OR available_since IS NULL OR unavailable_since >= available_since",
            name="ck_availability_availability_time_range",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            ondelete="SET NULL",
            name="fk_availability_evidence_id_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_availability_product_id_product",
        ),
        sa.ForeignKeyConstraint(
            ["region_id"],
            ["region.id"],
            ondelete="RESTRICT",
            name="fk_availability_region_id_region",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_availability"),
        sa.UniqueConstraint("product_id", "region_id", name="uq_availability_product_region"),
    )
    op.create_index("ix_availability_evidence_id", "availability", ["evidence_id"])
    op.create_index("ix_availability_product_id", "availability", ["product_id"])
    op.create_index("ix_availability_region_id", "availability", ["region_id"])

    op.create_table(
        "specification_definition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("canonical_unit", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "data_type IN ('numeric', 'text', 'boolean', 'enum')",
            name="ck_specification_definition_specification_definition_data_type",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["product_category.id"],
            ondelete="RESTRICT",
            name="fk_specification_definition_category_id_product_category",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_specification_definition"),
        sa.UniqueConstraint("code", name="uq_specification_definition_code"),
    )
    op.create_index(
        "ix_specification_definition_category_id", "specification_definition", ["category_id"]
    )
    op.create_index("ix_specification_definition_code", "specification_definition", ["code"])

    op.create_table(
        "product_specification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("definition_id", sa.Integer(), nullable=False),
        sa.Column("numeric_value", sa.Numeric(24, 8), nullable=True),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("boolean_value", sa.Boolean(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("raw_unit", sa.String(length=64), nullable=True),
        sa.Column("canonical_value", sa.String(length=256), nullable=True),
        sa.Column("canonical_unit", sa.String(length=64), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "(CASE WHEN numeric_value IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN text_value IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN boolean_value IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_product_specification_product_specification_exactly_one_value",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_product_specification_product_specification_valid_range",
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["specification_definition.id"],
            ondelete="RESTRICT",
            name="fk_product_specification_definition_id_specification_definition",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            ondelete="RESTRICT",
            name="fk_product_specification_evidence_id_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_product_specification_product_id_product",
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"], ["sku.id"], ondelete="RESTRICT", name="fk_product_specification_sku_id_sku"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_specification"),
    )
    op.create_index(
        "ix_product_specification_definition_id", "product_specification", ["definition_id"]
    )
    op.create_index(
        "ix_product_specification_evidence_id", "product_specification", ["evidence_id"]
    )
    op.create_index("ix_product_specification_product_id", "product_specification", ["product_id"])
    op.create_index("ix_product_specification_sku_id", "product_specification", ["sku_id"])

    op.create_table(
        "price_sku",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("provider_price_code", sa.String(length=128), nullable=False),
        sa.Column("charge_category", sa.String(length=64), nullable=False),
        sa.Column("billing_mode", sa.String(length=64), nullable=False),
        sa.Column("billing_unit", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("tax_included", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "charge_category IN ('compute', 'storage', 'request', 'traffic', 'license', 'support', 'unknown')",
            name="ck_price_sku_price_sku_charge_category",
        ),
        sa.CheckConstraint(
            "billing_mode IN ('on_demand', 'subscription', 'reserved', 'savings_plan', 'spot', 'tiered', 'request_based', 'traffic_based', 'unknown')",
            name="ck_price_sku_price_sku_billing_mode",
        ),
        sa.CheckConstraint("length(currency) = 3", name="ck_price_sku_price_sku_currency_len"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_price_sku_product_id_product",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["provider.id"],
            ondelete="RESTRICT",
            name="fk_price_sku_provider_id_provider",
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], ondelete="RESTRICT", name="fk_price_sku_region_id_region"
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"], ["sku.id"], ondelete="RESTRICT", name="fk_price_sku_sku_id_sku"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_price_sku"),
        sa.UniqueConstraint(
            "provider_id", "provider_price_code", name="uq_price_sku_provider_code"
        ),
    )
    op.create_index("ix_price_sku_product_id", "price_sku", ["product_id"])
    op.create_index("ix_price_sku_provider_id", "price_sku", ["provider_id"])
    op.create_index("ix_price_sku_region_id", "price_sku", ["region_id"])
    op.create_index("ix_price_sku_sku_id", "price_sku", ["sku_id"])

    op.create_table(
        "price_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("price_sku_id", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("minimum_quantity", sa.Numeric(24, 8), nullable=True),
        sa.Column("maximum_quantity", sa.Numeric(24, 8), nullable=True),
        sa.Column("billing_period", sa.String(length=64), nullable=True),
        sa.Column("discount_type", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("source_payload_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "unit_price >= 0", name="ck_price_snapshot_price_snapshot_unit_price_non_negative"
        ),
        sa.CheckConstraint(
            "minimum_quantity IS NULL OR minimum_quantity >= 0",
            name="ck_price_snapshot_price_snapshot_min_quantity_non_negative",
        ),
        sa.CheckConstraint(
            "maximum_quantity IS NULL OR maximum_quantity >= 0",
            name="ck_price_snapshot_price_snapshot_max_quantity_non_negative",
        ),
        sa.CheckConstraint(
            "maximum_quantity IS NULL OR minimum_quantity IS NULL OR maximum_quantity >= minimum_quantity",
            name="ck_price_snapshot_price_snapshot_quantity_range",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_price_snapshot_price_snapshot_effective_range",
        ),
        sa.CheckConstraint(
            "discount_type IN ('list', 'promotional', 'contract', 'estimated', 'unknown')",
            name="ck_price_snapshot_price_snapshot_discount_type",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            ondelete="RESTRICT",
            name="fk_price_snapshot_evidence_id_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["price_sku_id"],
            ["price_sku.id"],
            ondelete="RESTRICT",
            name="fk_price_snapshot_price_sku_id_price_sku",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_price_snapshot"),
    )
    op.create_index("ix_price_snapshot_evidence_id", "price_snapshot", ["evidence_id"])
    op.create_index("ix_price_snapshot_price_sku_id", "price_snapshot", ["price_sku_id"])

    op.create_table(
        "product_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_product_id", sa.Integer(), nullable=False),
        sa.Column("target_product_id", sa.Integer(), nullable=False),
        sa.Column("source_sku_id", sa.Integer(), nullable=True),
        sa.Column("target_sku_id", sa.Integer(), nullable=True),
        sa.Column("mapping_level", sa.String(length=64), nullable=False),
        sa.Column("mapping_status", sa.String(length=64), nullable=False),
        sa.Column("scenario_code", sa.String(length=128), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "mapping_level IN ('product', 'product_family', 'sku', 'scenario')",
            name="ck_product_mapping_product_mapping_level",
        ),
        sa.CheckConstraint(
            "mapping_status IN ('exact', 'comparable', 'partial', 'none', 'pending_review')",
            name="ck_product_mapping_product_mapping_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown')",
            name="ck_product_mapping_product_mapping_review_status",
        ),
        sa.CheckConstraint(
            "source_product_id <> target_product_id",
            name="ck_product_mapping_product_mapping_not_self_product",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            ondelete="SET NULL",
            name="fk_product_mapping_evidence_id_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_product_mapping_source_product_id_product",
        ),
        sa.ForeignKeyConstraint(
            ["source_sku_id"],
            ["sku.id"],
            ondelete="RESTRICT",
            name="fk_product_mapping_source_sku_id_sku",
        ),
        sa.ForeignKeyConstraint(
            ["target_product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_product_mapping_target_product_id_product",
        ),
        sa.ForeignKeyConstraint(
            ["target_sku_id"],
            ["sku.id"],
            ondelete="RESTRICT",
            name="fk_product_mapping_target_sku_id_sku",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_mapping"),
    )
    op.create_index("ix_product_mapping_evidence_id", "product_mapping", ["evidence_id"])
    op.create_index(
        "ix_product_mapping_source_product_id", "product_mapping", ["source_product_id"]
    )
    op.create_index("ix_product_mapping_source_sku_id", "product_mapping", ["source_sku_id"])
    op.create_index(
        "ix_product_mapping_target_product_id", "product_mapping", ["target_product_id"]
    )
    op.create_index("ix_product_mapping_target_sku_id", "product_mapping", ["target_sku_id"])

    op.create_table(
        "competitive_claim",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_mode", sa.String(length=32), nullable=False),
        sa.Column("source_product_id", sa.Integer(), nullable=False),
        sa.Column("target_product_id", sa.Integer(), nullable=False),
        sa.Column("scenario_code", sa.String(length=128), nullable=False),
        sa.Column("claim_type", sa.String(length=64), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("customer_value", sa.Text(), nullable=True),
        sa.Column("applicable_conditions", sa.Text(), nullable=False),
        sa.Column("limitations", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "market_mode IN ('domestic', 'international')",
            name="ck_competitive_claim_competitive_claim_market_mode",
        ),
        sa.CheckConstraint(
            "claim_type IN ('strength', 'limitation', 'cost_risk', 'migration_risk', 'availability_risk', 'operational_advantage', 'ecosystem_advantage', 'neutral_difference')",
            name="ck_competitive_claim_competitive_claim_type",
        ),
        sa.CheckConstraint(
            "review_status IN ('machine_extracted', 'pending_review', 'human_reviewed', 'rejected', 'unknown')",
            name="ck_competitive_claim_competitive_claim_review_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_competitive_claim_competitive_claim_confidence_range",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_competitive_claim_competitive_claim_valid_range",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            ondelete="RESTRICT",
            name="fk_competitive_claim_evidence_id_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_competitive_claim_source_product_id_product",
        ),
        sa.ForeignKeyConstraint(
            ["target_product_id"],
            ["product.id"],
            ondelete="RESTRICT",
            name="fk_competitive_claim_target_product_id_product",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_competitive_claim"),
    )
    op.create_index("ix_competitive_claim_evidence_id", "competitive_claim", ["evidence_id"])
    op.create_index(
        "ix_competitive_claim_source_product_id", "competitive_claim", ["source_product_id"]
    )
    op.create_index(
        "ix_competitive_claim_target_product_id", "competitive_claim", ["target_product_id"]
    )

    op.create_table(
        "sales_scenario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("market_mode", sa.String(length=32), nullable=False),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_weights_json", sa.JSON(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "market_mode IN ('domestic', 'international')",
            name="ck_sales_scenario_sales_scenario_market_mode",
        ),
        sa.CheckConstraint(
            "country_code IS NULL OR length(country_code) = 2",
            name="ck_sales_scenario_sales_country_len",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sales_scenario"),
        sa.UniqueConstraint("code", name="uq_sales_scenario_code"),
    )
    op.create_index("ix_sales_scenario_code", "sales_scenario", ["code"])

    op.create_table(
        "evaluation_case",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_code", sa.String(length=128), nullable=False),
        sa.Column("case_type", sa.String(length=64), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("expected_behavior", sa.Text(), nullable=False),
        sa.Column("expected_sources", sa.JSON(), nullable=True),
        sa.Column("risk_level", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "case_type IN ('product_mapping', 'availability', 'pricing', 'claim_grounding', 'unknown')",
            name="ck_evaluation_case_evaluation_case_type",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_case"),
        sa.UniqueConstraint("case_code", name="uq_evaluation_case_code"),
    )
    op.create_index("ix_evaluation_case_case_code", "evaluation_case", ["case_code"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_case_case_code", table_name="evaluation_case")
    op.drop_table("evaluation_case")
    op.drop_index("ix_sales_scenario_code", table_name="sales_scenario")
    op.drop_table("sales_scenario")
    op.drop_index("ix_competitive_claim_target_product_id", table_name="competitive_claim")
    op.drop_index("ix_competitive_claim_source_product_id", table_name="competitive_claim")
    op.drop_index("ix_competitive_claim_evidence_id", table_name="competitive_claim")
    op.drop_table("competitive_claim")
    op.drop_index("ix_product_mapping_target_sku_id", table_name="product_mapping")
    op.drop_index("ix_product_mapping_target_product_id", table_name="product_mapping")
    op.drop_index("ix_product_mapping_source_sku_id", table_name="product_mapping")
    op.drop_index("ix_product_mapping_source_product_id", table_name="product_mapping")
    op.drop_index("ix_product_mapping_evidence_id", table_name="product_mapping")
    op.drop_table("product_mapping")
    op.drop_index("ix_price_snapshot_price_sku_id", table_name="price_snapshot")
    op.drop_index("ix_price_snapshot_evidence_id", table_name="price_snapshot")
    op.drop_table("price_snapshot")
    op.drop_index("ix_price_sku_sku_id", table_name="price_sku")
    op.drop_index("ix_price_sku_region_id", table_name="price_sku")
    op.drop_index("ix_price_sku_provider_id", table_name="price_sku")
    op.drop_index("ix_price_sku_product_id", table_name="price_sku")
    op.drop_table("price_sku")
    op.drop_index("ix_product_specification_sku_id", table_name="product_specification")
    op.drop_index("ix_product_specification_product_id", table_name="product_specification")
    op.drop_index("ix_product_specification_evidence_id", table_name="product_specification")
    op.drop_index("ix_product_specification_definition_id", table_name="product_specification")
    op.drop_table("product_specification")
    op.drop_index("ix_specification_definition_code", table_name="specification_definition")
    op.drop_index("ix_specification_definition_category_id", table_name="specification_definition")
    op.drop_table("specification_definition")
    op.drop_index("ix_availability_region_id", table_name="availability")
    op.drop_index("ix_availability_product_id", table_name="availability")
    op.drop_index("ix_availability_evidence_id", table_name="availability")
    op.drop_table("availability")
    op.drop_index("ix_evidence_source_document_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_source_document_provider_id", table_name="source_document")
    op.drop_table("source_document")
    op.drop_index("ix_region_provider_id", table_name="region")
    op.drop_table("region")
    op.drop_index("ix_sku_product_id", table_name="sku")
    op.drop_table("sku")
    op.drop_index("ix_product_alias_product_id", table_name="product_alias")
    op.drop_table("product_alias")
    op.drop_index("ix_product_provider_id", table_name="product")
    op.drop_index("ix_product_category_id", table_name="product")
    op.drop_table("product")
    op.drop_index("ix_product_category_code", table_name="product_category")
    op.drop_table("product_category")
    op.drop_index("ix_provider_code", table_name="provider")
    op.drop_table("provider")
