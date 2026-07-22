"""Repository exports."""

from cloud_expert.database.repositories.canonical import (
    CanonicalFieldDefinitionRepository,
    ComparabilityAssessmentRepository,
    NormalizationRuleRepository,
    NormalizedSpecificationRepository,
)
from cloud_expert.database.repositories.ingestion import IngestionRunRepository
from cloud_expert.database.repositories.mapping import ProductMappingRepository
from cloud_expert.database.repositories.parsing import (
    ParsedFieldCandidateRepository,
    ParsingRunRepository,
)
from cloud_expert.database.repositories.pricing import PriceSnapshotRepository
from cloud_expert.database.repositories.product import ProductRepository
from cloud_expert.database.repositories.product_extension import (
    ProductFamilyRepository,
    ProductSLARepository,
    ServiceTierRepository,
)
from cloud_expert.database.repositories.provider import ProviderRepository
from cloud_expert.database.repositories.region import RegionRepository
from cloud_expert.database.repositories.review import (
    DataQualityIssueRepository,
    ReviewItemRepository,
)
from cloud_expert.database.repositories.snapshot import SnapshotRecordRepository
from cloud_expert.database.repositories.source import EvidenceRepository, SourceDocumentRepository

__all__ = [
    "CanonicalFieldDefinitionRepository",
    "ComparabilityAssessmentRepository",
    "EvidenceRepository",
    "IngestionRunRepository",
    "DataQualityIssueRepository",
    "NormalizationRuleRepository",
    "NormalizedSpecificationRepository",
    "ParsedFieldCandidateRepository",
    "ParsingRunRepository",
    "PriceSnapshotRepository",
    "ProductMappingRepository",
    "ProductFamilyRepository",
    "ProductSLARepository",
    "ProductRepository",
    "ProviderRepository",
    "RegionRepository",
    "ReviewItemRepository",
    "ServiceTierRepository",
    "SnapshotRecordRepository",
    "SourceDocumentRepository",
]
