"""SQLAlchemy model exports."""

from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    ComparabilityAssessment,
    NormalizationRule,
    NormalizationRun,
    NormalizedSpecification,
)
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.competition import CompetitiveClaim
from cloud_expert.database.models.evaluation import EvaluationCase, SalesScenario
from cloud_expert.database.models.ingestion import IngestionRun
from cloud_expert.database.models.mapping import ProductMapping
from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import (
    SKU,
    Product,
    ProductAlias,
    ProductCategory,
)
from cloud_expert.database.models.product_extension import ProductFamily, ProductSLA, ServiceTier
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import (
    Availability,
    AvailabilityZone,
    Region,
    ZoneAvailability,
)
from cloud_expert.database.models.review import DataQualityIssue, ReviewItem
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import (
    ProductSpecification,
    SpecificationDefinition,
)

__all__ = [
    "Availability",
    "AvailabilityZone",
    "CanonicalFieldDefinition",
    "CloudPartition",
    "ComparabilityAssessment",
    "CompetitiveClaim",
    "EvaluationCase",
    "Evidence",
    "IngestionRun",
    "DataQualityIssue",
    "NormalizationRule",
    "NormalizationRun",
    "NormalizedSpecification",
    "ParsedFieldCandidate",
    "PriceSKU",
    "PriceSnapshot",
    "Product",
    "ProductAlias",
    "ProductCategory",
    "ProductFamily",
    "ProductMapping",
    "ProductSLA",
    "ProductSpecification",
    "Provider",
    "ParsingRun",
    "Region",
    "ReviewItem",
    "SKU",
    "SalesScenario",
    "ServiceTier",
    "SnapshotRecord",
    "SourceDocument",
    "SpecificationDefinition",
    "ZoneAvailability",
]
