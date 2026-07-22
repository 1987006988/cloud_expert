from datetime import datetime

from pydantic import field_validator, model_validator

from cloud_expert.database.enums import AvailabilityStatus, MarketMode
from cloud_expert.schemas.base import (
    CountryCodeMixin,
    ListResponse,
    SchemaBase,
    TimestampReadSchema,
    validate_time_range,
)


class RegionBase(CountryCodeMixin):
    provider_id: int
    cloud_partition_id: int | None = None
    code: str
    name: str
    country_code: str
    geography: str | None = None
    market_mode: MarketMode
    is_active: bool = True


class RegionCreate(RegionBase):
    pass


class RegionUpdate(SchemaBase):
    cloud_partition_id: int | None = None
    name: str | None = None
    country_code: str | None = None
    geography: str | None = None
    market_mode: MarketMode | None = None
    is_active: bool | None = None

    @field_validator("country_code")
    @classmethod
    def _country_code(cls, value: str | None) -> str | None:
        from cloud_expert.schemas.base import validate_country_code

        return validate_country_code(value)


class RegionRead(RegionBase, TimestampReadSchema):
    pass


class RegionList(ListResponse):
    items: list[RegionRead]


class RegionFilter(SchemaBase):
    provider_id: int | None = None
    cloud_partition_id: int | None = None
    code: str | None = None
    country_code: str | None = None
    market_mode: MarketMode | None = None
    is_active: bool | None = None


class AvailabilityZoneBase(SchemaBase):
    provider_id: int
    region_id: int
    cloud_partition_id: int | None = None
    zone_code: str
    zone_name: str
    market_mode: MarketMode
    is_active: bool = True
    evidence_id: int | None = None


class AvailabilityZoneCreate(AvailabilityZoneBase):
    pass


class AvailabilityZoneUpdate(SchemaBase):
    cloud_partition_id: int | None = None
    zone_name: str | None = None
    market_mode: MarketMode | None = None
    is_active: bool | None = None
    evidence_id: int | None = None


class AvailabilityZoneRead(AvailabilityZoneBase, TimestampReadSchema):
    pass


class AvailabilityZoneList(ListResponse):
    items: list[AvailabilityZoneRead]


class AvailabilityZoneFilter(SchemaBase):
    provider_id: int | None = None
    region_id: int | None = None
    cloud_partition_id: int | None = None
    zone_code: str | None = None
    market_mode: MarketMode | None = None
    is_active: bool | None = None


class AvailabilityBase(SchemaBase):
    product_id: int
    region_id: int
    cloud_partition_id: int | None = None
    target_type: str = "product"
    target_code: str = "product"
    availability_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    public_preview: bool = False
    generally_available: bool = False
    available_since: datetime | None = None
    unavailable_since: datetime | None = None
    last_verified_at: datetime | None = None
    evidence_id: int | None = None

    @model_validator(mode="after")
    def _validate_availability(self) -> "AvailabilityBase":
        validate_time_range(self.available_since, self.unavailable_since)
        if (
            self.availability_status
            in {
                AvailabilityStatus.AVAILABLE,
                AvailabilityStatus.PREVIEW,
                AvailabilityStatus.LIMITED,
                AvailabilityStatus.AVAILABLE.value,
                AvailabilityStatus.PREVIEW.value,
                AvailabilityStatus.LIMITED.value,
            }
            and self.evidence_id is None
        ):
            msg = "positive availability conclusions require evidence_id"
            raise ValueError(msg)
        return self


class AvailabilityCreate(AvailabilityBase):
    pass


class AvailabilityUpdate(SchemaBase):
    cloud_partition_id: int | None = None
    target_type: str | None = None
    target_code: str | None = None
    availability_status: AvailabilityStatus | None = None
    public_preview: bool | None = None
    generally_available: bool | None = None
    available_since: datetime | None = None
    unavailable_since: datetime | None = None
    last_verified_at: datetime | None = None
    evidence_id: int | None = None


class AvailabilityRead(AvailabilityBase, TimestampReadSchema):
    pass


class ZoneAvailabilityBase(SchemaBase):
    product_id: int
    region_id: int
    availability_zone_id: int
    cloud_partition_id: int | None = None
    target_type: str = "product"
    target_code: str = "product"
    availability_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    public_preview: bool = False
    generally_available: bool = False
    available_since: datetime | None = None
    unavailable_since: datetime | None = None
    last_verified_at: datetime | None = None
    evidence_id: int | None = None

    @model_validator(mode="after")
    def _validate_zone_availability(self) -> "ZoneAvailabilityBase":
        validate_time_range(self.available_since, self.unavailable_since)
        if (
            self.availability_status
            in {
                AvailabilityStatus.AVAILABLE,
                AvailabilityStatus.PREVIEW,
                AvailabilityStatus.LIMITED,
                AvailabilityStatus.AVAILABLE.value,
                AvailabilityStatus.PREVIEW.value,
                AvailabilityStatus.LIMITED.value,
            }
            and self.evidence_id is None
        ):
            msg = "positive zone availability conclusions require evidence_id"
            raise ValueError(msg)
        return self


class ZoneAvailabilityCreate(ZoneAvailabilityBase):
    pass


class ZoneAvailabilityUpdate(SchemaBase):
    cloud_partition_id: int | None = None
    target_type: str | None = None
    target_code: str | None = None
    availability_status: AvailabilityStatus | None = None
    public_preview: bool | None = None
    generally_available: bool | None = None
    available_since: datetime | None = None
    unavailable_since: datetime | None = None
    last_verified_at: datetime | None = None
    evidence_id: int | None = None


class ZoneAvailabilityRead(ZoneAvailabilityBase, TimestampReadSchema):
    pass
