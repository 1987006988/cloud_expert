from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.repositories.base import BaseRepository


class PriceSnapshotRepository(BaseRepository[PriceSnapshot]):
    model = PriceSnapshot

    def list_for_price_sku(self, price_sku_id: int) -> list[PriceSnapshot]:
        return self.list({"price_sku_id": price_sku_id})
