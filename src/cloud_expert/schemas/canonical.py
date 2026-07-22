from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from cloud_expert.database.enums import (
    CanonicalDomain,
    ComparabilityStatus,
    DataType,
    NormalizationRuleType,
    NormalizationRunStatus,
    ReviewStatus,
    SpecificationScopeType,
    ValueQualifier,
)
from cloud_expert.schemas.base import ListResponse, SchemaBase, TimestampReadSchema


class CanonicalFieldDefinitionBase(SchemaBase):
    code: str
    name: str
    domain: CanonicalDomain
    category_id: int | None = None
    data_type: DataType
    canonical_unit: str | None = None
    unit_dimension: str | None = None
    default_qualifier: ValueQualifier = ValueQualifier.EXACT
    default_scope_type: SpecificationScopeType = SpecificationScopeType.PRODUCT
    description: str | None = None
    is_comparable: bool = True
    is_active: bool = True
    metadata_json: dict[str, Any] | None = None


class CanonicalFieldDefinitionCreate(CanonicalFieldDefinitionBase):
    pass


class CanonicalFieldDefinitionUpdate(SchemaBase):
    name: str | None = None
    category_id: int | None = None
    canonical_unit: str | None = None
    unit_dimension: str | None = None
    default_qualifier: ValueQualifier | None = None
    default_scope_type: SpecificationScopeType | None = None
    description: str | None = None
    is_comparable: bool | None = None
    is_active: bool | None = None
    metadata_json: dict[str, Any] | None = None


class CanonicalFieldDefinitionRead(CanonicalFieldDefinitionBase, TimestampReadSchema):
    pass


class CanonicalFieldDefinitionList(ListResponse):
    items: list[CanonicalFieldDefinitionRead]


class NormalizationRuleBase(SchemaBase):
    code: str
    version: str = "v1"
    rule_type: NormalizationRuleType
    source_field_code: str | None = None
    canonical_field_id: int | None = None
    source_unit: str | None = None
    canonical_unit: str | None = None
    value_qualifier: ValueQualifier = ValueQualifier.UNKNOWN
    scope_type: SpecificationScopeType = SpecificationScopeType.UNKNOWN
    description: str | None = None
    is_active: bool = True
    metadata_json: dict[str, Any] | None = None


class NormalizationRuleCreate(NormalizationRuleBase):
    pass


class NormalizationRuleRead(NormalizationRuleBase, TimestampReadSchema):
    pass


class NormalizationRuleList(ListResponse):
    items: list[NormalizationRuleRead]


class NormalizationRunBase(SchemaBase):
    run_key: str
    status: NormalizationRunStatus
    source_database_label: str | None = None
    product_filter: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    records_examined: int = Field(default=0, ge=0)
    records_created: int = Field(default=0, ge=0)
    records_updated: int = Field(default=0, ge=0)
    records_skipped: int = Field(default=0, ge=0)
    review_items_created: int = Field(default=0, ge=0)
    error_message: str | None = None


class NormalizationRunCreate(NormalizationRunBase):
    pass


class NormalizationRunRead(NormalizationRunBase):
    id: int
    created_at: datetime


class NormalizedSpecificationBase(SchemaBase):
    product_specification_id: int
    product_id: int
    sku_id: int | None = None
    canonical_field_id: int
    normalization_rule_id: int
    normalization_run_id: int | None = None
    evidence_id: int
    scope_type: SpecificationScopeType
    scope_identity: str
    value_qualifier: ValueQualifier
    numeric_value: Decimal | None = None
    text_value: str | None = None
    boolean_value: bool | None = None
    raw_value: str
    raw_unit: str | None = None
    canonical_value: str | None = None
    canonical_unit: str | None = None
    conversion_notes: str | None = None
    quality_score: Decimal | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    source_value_hash: str

    @model_validator(mode="after")
    def _validate_values(self) -> "NormalizedSpecificationBase":
        value_count = sum(
            value is not None for value in (self.numeric_value, self.text_value, self.boolean_value)
        )
        if value_count != 1:
            msg = "exactly one of numeric_value, text_value, boolean_value must be provided"
            raise ValueError(msg)
        return self


class NormalizedSpecificationCreate(NormalizedSpecificationBase):
    pass


class NormalizedSpecificationRead(NormalizedSpecificationBase, TimestampReadSchema):
    pass


class NormalizedSpecificationList(ListResponse):
    items: list[NormalizedSpecificationRead]


class ComparabilityAssessmentBase(SchemaBase):
    canonical_field_id: int
    source_product_id: int
    target_product_id: int
    normalization_run_id: int | None = None
    scope_type: SpecificationScopeType
    value_qualifier: ValueQualifier
    status: ComparabilityStatus
    reason_code: str
    explanation: str
    market_scope: str | None = None
    evidence_coverage_score: Decimal | None = Field(default=None, ge=0, le=1)
    unit_compatibility_score: Decimal | None = Field(default=None, ge=0, le=1)
    qualifier_compatibility_score: Decimal | None = Field(default=None, ge=0, le=1)
    scope_compatibility_score: Decimal | None = Field(default=None, ge=0, le=1)
    overall_score: Decimal | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW


class ComparabilityAssessmentCreate(ComparabilityAssessmentBase):
    pass


class ComparabilityAssessmentRead(ComparabilityAssessmentBase, TimestampReadSchema):
    pass


class ComparabilityAssessmentList(ListResponse):
    items: list[ComparabilityAssessmentRead]
