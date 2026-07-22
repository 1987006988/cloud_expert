from datetime import datetime

from cloud_expert.database.enums import MappingLevel, MappingStatus, ReviewStatus
from cloud_expert.schemas.base import ListResponse, SchemaBase, TimestampReadSchema


class ProductMappingBase(SchemaBase):
    source_product_id: int
    target_product_id: int
    source_sku_id: int | None = None
    target_sku_id: int | None = None
    mapping_level: MappingLevel
    mapping_status: MappingStatus
    scenario_code: str
    rationale: str | None = None
    evidence_id: int | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    reviewed_at: datetime | None = None


class ProductMappingCreate(ProductMappingBase):
    pass


class ProductMappingUpdate(SchemaBase):
    source_sku_id: int | None = None
    target_sku_id: int | None = None
    mapping_level: MappingLevel | None = None
    mapping_status: MappingStatus | None = None
    scenario_code: str | None = None
    rationale: str | None = None
    evidence_id: int | None = None
    review_status: ReviewStatus | None = None
    reviewed_at: datetime | None = None


class ProductMappingRead(ProductMappingBase, TimestampReadSchema):
    pass


class ProductMappingList(ListResponse):
    items: list[ProductMappingRead]


class ProductMappingFilter(SchemaBase):
    source_product_id: int | None = None
    target_product_id: int | None = None
    mapping_level: MappingLevel | None = None
    mapping_status: MappingStatus | None = None
    scenario_code: str | None = None
    review_status: ReviewStatus | None = None
