from datetime import datetime

from pydantic import Field, model_validator

from cloud_expert.database.enums import ClaimType, MarketMode, ReviewStatus
from cloud_expert.schemas.base import (
    ConfidenceMixin,
    ListResponse,
    SchemaBase,
    TimestampReadSchema,
    validate_time_range,
)


class CompetitiveClaimBase(ConfidenceMixin):
    market_mode: MarketMode
    source_product_id: int
    target_product_id: int
    scenario_code: str
    claim_type: ClaimType
    claim_text: str
    customer_value: str | None = None
    applicable_conditions: str
    limitations: str
    evidence_id: int
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> "CompetitiveClaimBase":
        validate_time_range(self.valid_from, self.valid_to)
        return self


class CompetitiveClaimCreate(CompetitiveClaimBase):
    pass


class CompetitiveClaimUpdate(SchemaBase):
    claim_text: str | None = None
    customer_value: str | None = None
    applicable_conditions: str | None = None
    limitations: str | None = None
    evidence_id: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> "CompetitiveClaimUpdate":
        validate_time_range(self.valid_from, self.valid_to)
        return self


class CompetitiveClaimRead(CompetitiveClaimBase, TimestampReadSchema):
    pass


class CompetitiveClaimList(ListResponse):
    items: list[CompetitiveClaimRead]


class CompetitiveClaimFilter(SchemaBase):
    market_mode: MarketMode | None = None
    source_product_id: int | None = None
    target_product_id: int | None = None
    scenario_code: str | None = None
    claim_type: ClaimType | None = None
    review_status: ReviewStatus | None = None
