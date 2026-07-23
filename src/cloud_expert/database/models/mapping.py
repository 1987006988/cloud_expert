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
    FieldComparisonStatus,
    MappingCandidateStatus,
    MappingEvidenceRole,
    MappingLevel,
    MappingRelationshipType,
    MappingStatus,
    ReviewStatus,
    RuleSetStatus,
    sql_in_values,
)

if TYPE_CHECKING:
    from cloud_expert.database.models.canonical import (
        CanonicalFieldDefinition,
        NormalizedSpecification,
    )
    from cloud_expert.database.models.product import SKU, Product
    from cloud_expert.database.models.provider import Provider
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


class MappingRuleSet(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint("rule_set_code", "rule_set_version", name="uq_mapping_rule_set_version"),
        CheckConstraint(
            f"mapping_level IN ({sql_in_values(MappingLevel.values())})",
            name="mapping_rule_set_level",
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(RuleSetStatus.values())})",
            name="mapping_rule_set_status",
        ),
    )

    rule_set_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    rule_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_level: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    market_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    required_fields: Mapped[list[str] | None] = mapped_column(JSON)
    optional_fields: Mapped[list[str] | None] = mapped_column(JSON)
    exclusion_rules: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    scoring_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    candidates: Mapped[list["MappingCandidate"]] = relationship(back_populates="rule_set")


class MappingCandidate(IDMixin, TimestampMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "rule_set_id",
            "source_entity_type",
            "source_entity_id",
            "target_entity_type",
            "target_entity_id",
            "mapping_level",
            name="uq_mapping_candidate_natural_key",
        ),
        CheckConstraint(
            f"mapping_level IN ({sql_in_values(MappingLevel.values())})",
            name="mapping_candidate_level",
        ),
        CheckConstraint(
            f"relationship_type IN ({sql_in_values(MappingRelationshipType.values())})",
            name="mapping_candidate_relationship_type",
        ),
        CheckConstraint(
            f"candidate_status IN ({sql_in_values(MappingCandidateStatus.values())})",
            name="mapping_candidate_status",
        ),
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="mapping_candidate_review_status",
        ),
        CheckConstraint(
            "raw_score IS NULL OR (raw_score >= 0 AND raw_score <= 100)",
            name="mapping_candidate_raw_score",
        ),
        CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 1)",
            name="mapping_candidate_normalized_score",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="mapping_candidate_confidence",
        ),
    )

    mapping_level: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_id: Mapped[int] = mapped_column(nullable=False, index=True)
    target_provider_id: Mapped[int] = mapped_column(
        ForeignKey("provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[int] = mapped_column(nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_status: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_set_id: Mapped[int] = mapped_column(
        ForeignKey("mapping_rule_set.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    normalized_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    blocking_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    conditions: Mapped[list[str] | None] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("mapping_candidate.id", ondelete="SET NULL"),
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ReviewStatus.PENDING_REVIEW.value,
    )

    source_provider: Mapped["Provider"] = relationship(foreign_keys=[source_provider_id])
    target_provider: Mapped["Provider"] = relationship(foreign_keys=[target_provider_id])
    rule_set: Mapped[MappingRuleSet] = relationship(back_populates="candidates")
    superseded_by: Mapped["MappingCandidate | None"] = relationship(
        remote_side="MappingCandidate.id"
    )
    evidence_links: Mapped[list["MappingCandidateEvidence"]] = relationship(
        back_populates="candidate"
    )
    field_comparisons: Mapped[list["MappingFieldComparison"]] = relationship(
        back_populates="candidate"
    )
    reviews: Mapped[list["MappingReview"]] = relationship(back_populates="candidate")


class MappingCandidateEvidence(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "mapping_candidate_id",
            "evidence_id",
            "evidence_role",
            name="uq_mapping_candidate_evidence_role",
        ),
        CheckConstraint(
            f"evidence_role IN ({sql_in_values(MappingEvidenceRole.values())})",
            name="mapping_candidate_evidence_role",
        ),
    )

    mapping_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("mapping_candidate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_role: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    candidate: Mapped[MappingCandidate] = relationship(back_populates="evidence_links")
    evidence: Mapped["Evidence"] = relationship()


class MappingFieldComparison(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        UniqueConstraint(
            "mapping_candidate_id",
            "canonical_field_id",
            "source_value_id",
            "target_value_id",
            name="uq_mapping_field_comparison_identity",
        ),
        CheckConstraint(
            f"semantic_status IN ({sql_in_values(FieldComparisonStatus.values())})",
            name="mapping_field_semantic_status",
        ),
        CheckConstraint(
            f"unit_status IN ({sql_in_values(FieldComparisonStatus.values())})",
            name="mapping_field_unit_status",
        ),
        CheckConstraint(
            f"scope_status IN ({sql_in_values(FieldComparisonStatus.values())})",
            name="mapping_field_scope_status",
        ),
        CheckConstraint(
            f"qualifier_status IN ({sql_in_values(FieldComparisonStatus.values())})",
            name="mapping_field_qualifier_status",
        ),
        CheckConstraint(
            f"evidence_status IN ({sql_in_values(FieldComparisonStatus.values())})",
            name="mapping_field_evidence_status",
        ),
        CheckConstraint(
            f"comparison_status IN ({sql_in_values(FieldComparisonStatus.values())})",
            name="mapping_field_comparison_status",
        ),
        CheckConstraint(
            "similarity_score IS NULL OR (similarity_score >= 0 AND similarity_score <= 1)",
            name="mapping_field_similarity_score",
        ),
    )

    mapping_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("mapping_candidate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    canonical_field_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_field_definition.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalized_specification.id", ondelete="RESTRICT"),
        index=True,
    )
    target_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalized_specification.id", ondelete="RESTRICT"),
        index=True,
    )
    semantic_status: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_status: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_status: Mapped[str] = mapped_column(String(64), nullable=False)
    qualifier_status: Mapped[str] = mapped_column(String(64), nullable=False)
    freshness_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    evidence_status: Mapped[str] = mapped_column(String(64), nullable=False)
    comparison_status: Mapped[str] = mapped_column(String(64), nullable=False)
    similarity_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    blocking_reason: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    candidate: Mapped[MappingCandidate] = relationship(back_populates="field_comparisons")
    canonical_field: Mapped["CanonicalFieldDefinition"] = relationship()
    source_value: Mapped["NormalizedSpecification | None"] = relationship(
        foreign_keys=[source_value_id]
    )
    target_value: Mapped["NormalizedSpecification | None"] = relationship(
        foreign_keys=[target_value_id]
    )


class MappingReview(IDMixin, TableNameMixin, ReprMixin, Base):
    __table_args__ = (
        CheckConstraint(
            f"review_status IN ({sql_in_values(ReviewStatus.values())})",
            name="mapping_review_status",
        ),
        CheckConstraint(
            "corrected_relationship_type IS NULL "
            f"OR corrected_relationship_type IN ({sql_in_values(MappingRelationshipType.values())})",
            name="mapping_review_corrected_relationship_type",
        ),
    )

    mapping_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("mapping_candidate.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    review_status: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    corrected_relationship_type: Mapped[str | None] = mapped_column(String(64))
    corrected_target_entity_id: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    candidate: Mapped[MappingCandidate] = relationship(back_populates="reviews")
