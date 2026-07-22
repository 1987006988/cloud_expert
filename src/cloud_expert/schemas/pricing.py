from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from cloud_expert.database.enums import BillingMode, ChargeCategory, DiscountType
from cloud_expert.schemas.base import (
    CurrencyMixin,
    ListResponse,
    ReadSchema,
    SchemaBase,
    TimestampReadSchema,
    validate_time_range,
)


class PriceSKUBase(CurrencyMixin):
    provider_id: int
    product_id: int
    sku_id: int | None = None
    region_id: int
    provider_price_code: str
    charge_category: ChargeCategory
    billing_mode: BillingMode
    billing_unit: str
    currency: str
    tax_included: bool = False


class PriceSKUCreate(PriceSKUBase):
    pass


class PriceSKUUpdate(SchemaBase):
    sku_id: int | None = None
    charge_category: ChargeCategory | None = None
    billing_mode: BillingMode | None = None
    billing_unit: str | None = None
    currency: str | None = None
    tax_included: bool | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from cloud_expert.schemas.base import validate_currency

        return validate_currency(value)


class PriceSKURead(PriceSKUBase, TimestampReadSchema):
    pass


class PriceSKUList(ListResponse):
    items: list[PriceSKURead]


class PriceSKUFilter(SchemaBase):
    provider_id: int | None = None
    product_id: int | None = None
    sku_id: int | None = None
    region_id: int | None = None
    billing_mode: BillingMode | None = None
    currency: str | None = None


class PriceSnapshotBase(SchemaBase):
    price_sku_id: int
    unit_price: Decimal = Field(ge=0)
    minimum_quantity: Decimal | None = Field(default=None, ge=0)
    maximum_quantity: Decimal | None = Field(default=None, ge=0)
    billing_period: str | None = None
    discount_type: DiscountType = DiscountType.UNKNOWN
    captured_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    evidence_id: int
    source_payload_path: str | None = None

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "PriceSnapshotBase":
        if (
            self.minimum_quantity is not None
            and self.maximum_quantity is not None
            and self.maximum_quantity < self.minimum_quantity
        ):
            msg = "maximum_quantity must be greater than or equal to minimum_quantity"
            raise ValueError(msg)
        validate_time_range(self.effective_from, self.effective_to)
        return self


class PriceSnapshotCreate(PriceSnapshotBase):
    pass


class PriceSnapshotUpdate(SchemaBase):
    unit_price: Decimal | None = Field(default=None, ge=0)
    minimum_quantity: Decimal | None = Field(default=None, ge=0)
    maximum_quantity: Decimal | None = Field(default=None, ge=0)
    billing_period: str | None = None
    discount_type: DiscountType | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    evidence_id: int | None = None
    source_payload_path: str | None = None

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "PriceSnapshotUpdate":
        if (
            self.minimum_quantity is not None
            and self.maximum_quantity is not None
            and self.maximum_quantity < self.minimum_quantity
        ):
            msg = "maximum_quantity must be greater than or equal to minimum_quantity"
            raise ValueError(msg)
        validate_time_range(self.effective_from, self.effective_to)
        return self


class PriceSnapshotRead(PriceSnapshotBase, ReadSchema):
    captured_at: datetime
    created_at: datetime


class PriceSnapshotList(ListResponse):
    items: list[PriceSnapshotRead]


class PriceSnapshotFilter(SchemaBase):
    price_sku_id: int | None = None
    evidence_id: int | None = None
    discount_type: DiscountType | None = None
    captured_after: datetime | None = None
