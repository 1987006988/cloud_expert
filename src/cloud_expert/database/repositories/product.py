from cloud_expert.database.models.product import Product
from cloud_expert.database.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    model = Product

    def list_by_provider(self, provider_id: int) -> list[Product]:
        return self.list({"provider_id": provider_id})
