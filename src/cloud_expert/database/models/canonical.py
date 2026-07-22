from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cloud_expert.database.base import Base, IDMixin, ReprMixin, TableNameMixin, TimestampMixin
from cloud_expert.database.enums import (
    CanonicalDomain,
    ComparabilityStatus,
    DataType,
    NormalizationRuleType,
    NormalizationRunStatus,
    ReviewStatus,
    SpecificationScopeType,
    ValueQualifier,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.product import SKU, Product, ProductCategory
    from cloud_expert.database.models.source import Evidence
    from cloud_expert.database.models.specification import ProductSpecification


class CanonicalFieldDefinition(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("code", name="uq_canonical_field_definition_code"),
        CheckConstraint(
            f"domain IN ({sql_in_values(CanonicalDomain.values())})",
            name="canonical_field_definition_domain",
        ),
        CheckConstraint(
            f"data_type IN ({sql_in_values(DataType.values())})",
            name="canonical_field_definition_data_type",
        ),
        CheckConstraint(
            f"default_qualifier IN ({sql_in_values(ValueQualifier.values())})",
            name="canonical_field_definition_default_qualifier",
        ),
        CheckConstraint(
            f"default_scope_type IN ({sql_in_values(SpecificationScopeType.values())})",
            name="canonical_field_definition_default_scope",
        ),
    )

    code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_category.id", ondelete="SET NULL"),
        index=True,
    )
    data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_unit: Mapped[str | None] = mapped_column(String(64))
    unit_dimension: Mapped[str | None] = mapped_column(String(64))
    default_qualifier: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ValueQualifier.EXACT.value,
    )
    default_scope_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=SpecificationScopeType.PRODUCT.value,
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_comparable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    category: Mapped["ProductCategory | None"] = relationship()


class NormalizationRule(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_normalization_rule_code_version"),
        CheckConstraint(
            f"rule_type IN ({sql_in_values(NormalizationRuleType.values())})",
            name="normalization_rule_type",
        ),
        CheckConstraint(
            f"value_qualifier IN ({sql_in_values(ValueQualifier.values())})",
            name="normalization_rule_value_qualifier",
        ),
        CheckConstraint(
            f"scope_type IN ({sql_in_values(SpecificationScopeType.values())})",
            name="normalization_rule_scope_type",
        ),
    )

    code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_field_code: Mapped[str | None] = mapped_column(String(160), index=True)
    canonical_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_field_definition.id", ondelete="SET NULL"),
        index=True,
    )
    source_unit: Mapped[str | None] = mapped_column(String(64))
    canonical_unit: Mapped[str | None] = mapped_column(String(64))
    value_qualifier: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ValueQualifier.UNKNOWN.value,
    )
    scope_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=SpecificationScopeType.UNKNOWN.value,
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    canonical_field: Mapped[CanonicalFieldDefinition | None] = relationship()


class NormalizationRun(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_normalization_run_key"),
        CheckConstraint(
            f"status IN ({sql_in_values(NormalizationRunStatus.values())})",
            name="normalization_run_status",
        ),
    )

    run_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_database_label: Mapped[str | None] = mapped_column(String(256))
    product_filter: Mapped[str | None] = mapped_column(String(256))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_examined: Mapped[int] = mapped_column(nullable=False, default=0)
    records_created: Mapped[int] = mapped_column(nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(nullable=False, default=0)
    records_skipped: Mapped[int] = mapped_column(nullable=False, default=0)
    review_items_created: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class NormalizedSpecification(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "product_specification_id",
            "canonical_field_id",
            "scope_type",
            "scope_identity",
            "value_qualifier",
            name="uq_normalized_specification_identity",
        ),
        CheckConstraint(
            "(CASE WHEN numeric_value IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN text_value IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN boolean_value IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="normalized_specification_exactly_one_value",
        ),
        CheckConstraint(
            f"scope_type IN ({sql_in_values(SpecificationScopeType.values())})",
            name="normalized_specification_scope_type",
        ),
        CheckConstraint(
            f"value_qualifier IN ({sql_in_values(ValueQualifier.values())})",
            name="normalized_specification_value_qualifier",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="normalized_specification_review_status",
        ),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)",
            name="normalized_specification_quality_score",
        ),
    )

    product_specification_id: Mapped[int] = mapped_column(
        ForeignKey("product_specification.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("sku.id", ondelete="RESTRICT"),
        index=True,
    )
    canonical_field_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_field_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    normalization_rule_id: Mapped[int] = mapped_column(
        ForeignKey("normalization_rule.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    normalization_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalization_run.id", ondelete="SET NULL"),
        index=True,
    )
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    value_qualifier: Mapped[str] = mapped_column(String(64), nullable=False)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    text_value: Mapped[str | None] = mapped_column(Text)
    boolean_value: Mapped[bool | None] = mapped_column(Boolean)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    raw_unit: Mapped[str | None] = mapped_column(String(64))
    canonical_value: Mapped[str | None] = mapped_column(String(256))
    canonical_unit: Mapped[str | None] = mapped_column(String(64))
    conversion_notes: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    review_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ReviewStatus.PENDING_REVIEW.value,
    )
    source_value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    product_specification: Mapped["ProductSpecification"] = relationship()
    product: Mapped["Product"] = relationship()
    sku: Mapped["SKU | None"] = relationship()
    canonical_field: Mapped[CanonicalFieldDefinition] = relationship()
    normalization_rule: Mapped[NormalizationRule] = relationship()
    normalization_run: Mapped[NormalizationRun | None] = relationship()
    evidence: Mapped["Evidence"] = relationship()


class ComparabilityAssessment(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "canonical_field_id",
            "source_product_id",
            "target_product_id",
            "scope_type",
            "value_qualifier",
            name="uq_comparability_assessment_identity",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(ComparabilityStatus.values())})",
            name="comparability_assessment_status",
        ),
        CheckConstraint(
            f"scope_type IN ({sql_in_values(SpecificationScopeType.values())})",
            name="comparability_assessment_scope_type",
        ),
        CheckConstraint(
            f"value_qualifier IN ({sql_in_values(ValueQualifier.values())})",
            name="comparability_assessment_value_qualifier",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="comparability_assessment_review_status",
        ),
        CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 1)",
            name="comparability_assessment_overall_score",
        ),
    )

    canonical_field_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_field_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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
    normalization_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalization_run.id", ondelete="SET NULL"),
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_qualifier: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    market_scope: Mapped[str | None] = mapped_column(String(128))
    evidence_coverage_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    unit_compatibility_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    qualifier_compatibility_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    scope_compatibility_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    review_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ReviewStatus.PENDING_REVIEW.value,
    )

    canonical_field: Mapped[CanonicalFieldDefinition] = relationship()
    source_product: Mapped["Product"] = relationship(foreign_keys=[source_product_id])
    target_product: Mapped["Product"] = relationship(foreign_keys=[target_product_id])
    normalization_run: Mapped[NormalizationRun | None] = relationship()
