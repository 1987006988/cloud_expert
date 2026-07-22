from cloud_expert.database.models.provider import Provider
from cloud_expert.database.repositories.base import BaseRepository


class ProviderRepository(BaseRepository[Provider]):
    model = Provider

    def get_by_code(self, code: str) -> Provider | None:
        return next(iter(self.list({"code": code}, limit=1)), None)
