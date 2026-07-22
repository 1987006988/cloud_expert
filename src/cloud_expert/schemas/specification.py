from datetime import datetime
from decimal import Decimal

from pydantic import Field, model_validator

from cloud_expert.database.enums import DataType
from cloud_expert.schemas.base import (
    ListResponse,
    SchemaBase,
    TimestampReadSchema,
    validate_time_range,
)


class SpecificationDefinitionBase(SchemaBase):
    code: str
    name: str
    category_id: int
    data_type: DataType
    canonical_unit: str | None = None
    description: str | None = None
    is_required: bool = False


class SpecificationDefinitionCreate(SpecificationDefinitionBase):
    pass


class SpecificationDefinitionUpdate(SchemaBase):
    name: str | None = None
    category_id: int | None = None
    data_type: DataType | None = None
    canonical_unit: str | None = None
    description: str | None = None
    is_required: bool | None = None


class SpecificationDefinitionRead(SpecificationDefinitionBase, TimestampReadSchema):
    pass


class SpecificationDefinitionList(ListResponse):
    items: list[SpecificationDefinitionRead]


class SpecificationDefinitionFilter(SchemaBase):
    code: str | None = None
    category_id: int | None = None
    data_type: DataType | None = None
    is_required: bool | None = None


class ProductSpecificationBase(SchemaBase):
    product_id: int
    sku_id: int | None = None
    definition_id: int
    numeric_value: Decimal | None = None
    text_value: str | None = None
    boolean_value: bool | None = None
    raw_value: str
    raw_unit: str | None = None
    canonical_value: str | None = None
    canonical_unit: str | None = None
    evidence_id: int
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    last_verified_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_values(self) -> "ProductSpecificationBase":
        value_count = sum(
            value is not None for value in (self.numeric_value, self.text_value, self.boolean_value)
        )
        if value_count != 1:
            msg = "exactly one of numeric_value, text_value, boolean_value must be provided"
            raise ValueError(msg)
        validate_time_range(self.valid_from, self.valid_to)
        return self


class ProductSpecificationCreate(ProductSpecificationBase):
    pass


class ProductSpecificationUpdate(SchemaBase):
    numeric_value: Decimal | None = Field(default=None)
    text_value: str | None = None
    boolean_value: bool | None = None
    raw_value: str | None = None
    raw_unit: str | None = None
    canonical_value: str | None = None
    canonical_unit: str | None = None
    evidence_id: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    last_verified_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> "ProductSpecificationUpdate":
        validate_time_range(self.valid_from, self.valid_to)
        return self


class ProductSpecificationRead(ProductSpecificationBase, TimestampReadSchema):
    pass


class ProductSpecificationList(ListResponse):
    items: list[ProductSpecificationRead]


class ProductSpecificationFilter(SchemaBase):
    product_id: int | None = None
    sku_id: int | None = None
    definition_id: int | None = None
    evidence_id: int | None = None
