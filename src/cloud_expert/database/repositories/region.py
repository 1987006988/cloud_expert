from cloud_expert.database.models.region import AvailabilityZone, Region, ZoneAvailability
from cloud_expert.database.repositories.base import BaseRepository


class RegionRepository(BaseRepository[Region]):
    model = Region

    def list_by_provider(self, provider_id: int) -> list[Region]:
        return self.list({"provider_id": provider_id})


class AvailabilityZoneRepository(BaseRepository[AvailabilityZone]):
    model = AvailabilityZone

    def list_by_region(self, region_id: int) -> list[AvailabilityZone]:
        return self.list({"region_id": region_id})


class ZoneAvailabilityRepository(BaseRepository[ZoneAvailability]):
    model = ZoneAvailability

    def list_by_zone(self, availability_zone_id: int) -> list[ZoneAvailability]:
        return self.list({"availability_zone_id": availability_zone_id})
