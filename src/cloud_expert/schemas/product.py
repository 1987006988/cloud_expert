from datetime import datetime
from typing import Any

from pydantic import field_validator

from cloud_expert.database.enums import AliasType, MarketMode, ProductStatus, SKUStatus
from cloud_expert.schemas.base import (
    ListResponse,
    ReadSchema,
    SchemaBase,
    TimestampReadSchema,
    validate_url,
)


class ProductCategoryBase(SchemaBase):
    code: str
    name: str
    parent_id: int | None = None
    description: str | None = None


class ProductCategoryCreate(ProductCategoryBase):
    pass


class ProductCategoryUpdate(SchemaBase):
    name: str | None = None
    parent_id: int | None = None
    description: str | None = None


class ProductCategoryRead(ProductCategoryBase, TimestampReadSchema):
    pass


class ProductCategoryList(ListResponse):
    items: list[ProductCategoryRead]


class ProductCategoryFilter(SchemaBase):
    code: str | None = None
    parent_id: int | None = None


class ProductBase(SchemaBase):
    provider_id: int
    category_id: int
    market_mode: MarketMode
    code: str
    official_name: str
    display_name: str
    description: str | None = None
    product_status: ProductStatus = ProductStatus.UNKNOWN
    official_url: str | None = None
    documentation_url: str | None = None
    first_seen_at: datetime | None = None
    last_verified_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("official_url", "documentation_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return validate_url(value)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(SchemaBase):
    category_id: int | None = None
    official_name: str | None = None
    display_name: str | None = None
    description: str | None = None
    product_status: ProductStatus | None = None
    official_url: str | None = None
    documentation_url: str | None = None
    first_seen_at: datetime | None = None
    last_verified_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("official_url", "documentation_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return validate_url(value)


class ProductRead(ProductBase, TimestampReadSchema):
    pass


class ProductList(ListResponse):
    items: list[ProductRead]


class ProductFilter(SchemaBase):
    provider_id: int | None = None
    category_id: int | None = None
    market_mode: MarketMode | None = None
    code: str | None = None
    product_status: ProductStatus | None = None


class ProductAliasBase(SchemaBase):
    product_id: int
    alias: str
    alias_type: AliasType
    language: str = "unknown"
    is_official: bool = False


class ProductAliasCreate(ProductAliasBase):
    pass


class ProductAliasUpdate(SchemaBase):
    alias: str | None = None
    alias_type: AliasType | None = None
    language: str | None = None
    is_official: bool | None = None


class ProductAliasRead(ProductAliasBase, ReadSchema):
    created_at: datetime


class ProductAliasList(ListResponse):
    items: list[ProductAliasRead]


class ProductAliasFilter(SchemaBase):
    product_id: int | None = None
    alias_type: AliasType | None = None
    language: str | None = None


class SKUBase(SchemaBase):
    product_id: int
    provider_sku_code: str
    name: str
    sku_family: str | None = None
    architecture: str | None = None
    operating_system: str | None = None
    status: SKUStatus = SKUStatus.UNKNOWN


class SKUCreate(SKUBase):
    pass


class SKUUpdate(SchemaBase):
    name: str | None = None
    sku_family: str | None = None
    architecture: str | None = None
    operating_system: str | None = None
    status: SKUStatus | None = None


class SKURead(SKUBase, TimestampReadSchema):
    pass


class SKUList(ListResponse):
    items: list[SKURead]


class SKUFilter(SchemaBase):
    product_id: int | None = None
    provider_sku_code: str | None = None
    status: SKUStatus | None = None
