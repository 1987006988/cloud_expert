from cloud_expert.database.models.mapping import ProductMapping
from cloud_expert.database.repositories.base import BaseRepository


class ProductMappingRepository(BaseRepository[ProductMapping]):
    model = ProductMapping

    def list_for_source_product(self, source_product_id: int) -> list[ProductMapping]:
        return self.list({"source_product_id": source_product_id})
