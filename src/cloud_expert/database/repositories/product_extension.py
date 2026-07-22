from cloud_expert.database.models.product_extension import ProductFamily, ProductSLA, ServiceTier
from cloud_expert.database.repositories.base import BaseRepository


class ProductFamilyRepository(BaseRepository[ProductFamily]):
    model = ProductFamily


class ServiceTierRepository(BaseRepository[ServiceTier]):
    model = ServiceTier


class ProductSLARepository(BaseRepository[ProductSLA]):
    model = ProductSLA
