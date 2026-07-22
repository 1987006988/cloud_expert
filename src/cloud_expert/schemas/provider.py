from datetime import datetime

from pydantic import field_validator

from cloud_expert.schemas.base import ListResponse, SchemaBase, TimestampReadSchema, validate_url


class ProviderBase(SchemaBase):
    code: str
    name: str
    display_name: str
    provider_type: str = "public_cloud"
    official_website: str | None = None
    is_active: bool = True

    @field_validator("official_website")
    @classmethod
    def _official_website(cls, value: str | None) -> str | None:
        return validate_url(value)


class ProviderCreate(ProviderBase):
    pass


class ProviderUpdate(SchemaBase):
    name: str | None = None
    display_name: str | None = None
    provider_type: str | None = None
    official_website: str | None = None
    is_active: bool | None = None

    @field_validator("official_website")
    @classmethod
    def _official_website(cls, value: str | None) -> str | None:
        return validate_url(value)


class ProviderRead(ProviderBase, TimestampReadSchema):
    pass


class ProviderList(ListResponse):
    items: list[ProviderRead]


class ProviderFilter(SchemaBase):
    code: str | None = None
    provider_type: str | None = None
    is_active: bool | None = None
    created_after: datetime | None = None
