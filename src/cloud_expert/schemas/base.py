from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SchemaBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ReadSchema(SchemaBase):
    id: int


class TimestampReadSchema(ReadSchema):
    created_at: datetime
    updated_at: datetime


class ListResponse(SchemaBase):
    total: int = Field(ge=0)
    items: list[Any]


def validate_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = "URL must be an absolute http(s) URL"
        raise ValueError(msg)
    return value


def validate_country_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.upper()
    if len(normalized) != 2 or not normalized.isalpha():
        msg = "country_code must be a 2-letter ISO-like code"
        raise ValueError(msg)
    return normalized


def validate_currency(value: str) -> str:
    normalized = value.upper()
    if len(normalized) != 3 or not normalized.isalpha():
        msg = "currency must be a 3-letter ISO-like code"
        raise ValueError(msg)
    return normalized


def validate_time_range(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and end < start:
        msg = "end timestamp must not be earlier than start timestamp"
        raise ValueError(msg)


class ConfidenceMixin(SchemaBase):
    confidence: float = Field(ge=0, le=1)


class EffectiveRangeMixin(SchemaBase):
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    @model_validator(mode="after")
    def _validate_effective_range(self) -> "EffectiveRangeMixin":
        validate_time_range(self.effective_from, self.effective_to)
        return self


class ValidRangeMixin(SchemaBase):
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def _validate_valid_range(self) -> "ValidRangeMixin":
        validate_time_range(self.valid_from, self.valid_to)
        return self


class CountryCodeMixin(SchemaBase):
    country_code: str | None = None

    @field_validator("country_code")
    @classmethod
    def _country_code(cls, value: str | None) -> str | None:
        return validate_country_code(value)


class CurrencyMixin(SchemaBase):
    currency: str

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency(value)


def quantize_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
