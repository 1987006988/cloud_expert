from enum import StrEnum


class StableStrEnum(StrEnum):
    """String enum with stable database values."""

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class MarketMode(StableStrEnum):
    DOMESTIC = "domestic"
    INTERNATIONAL = "international"


class ProductStatus(StableStrEnum):
    ACTIVE = "active"
    PREVIEW = "preview"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class AvailabilityStatus(StableStrEnum):
    AVAILABLE = "available"
    PREVIEW = "preview"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    RETIRED = "retired"


class SourceType(StableStrEnum):
    PRODUCT_PAGE = "product_page"
    DOCUMENTATION = "documentation"
    SPECIFICATION = "specification"
    PRICING = "pricing"
    SLA = "sla"
    REGION_AVAILABILITY = "region_availability"
    RELEASE_NOTE = "release_note"
    COMPLIANCE = "compliance"
    API_RESPONSE = "api_response"
    INTERNAL_REVIEW = "internal_review"


class AuthorityLevel(StableStrEnum):
    OFFICIAL_PRIMARY = "official_primary"
    OFFICIAL_SECONDARY = "official_secondary"
    PARTNER = "partner"
    THIRD_PARTY = "third_party"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class ReviewStatus(StableStrEnum):
    MACHINE_EXTRACTED = "machine_extracted"
    PENDING_REVIEW = "pending_review"
    HUMAN_REVIEWED = "human_reviewed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class CanonicalDomain(StableStrEnum):
    COMPUTE = "compute"
    OBJECT_STORAGE = "object_storage"
    REGION = "region"
    SLA = "sla"
    PRODUCT_METADATA = "product_metadata"


class ValueQualifier(StableStrEnum):
    EXACT = "exact"
    BASELINE = "baseline"
    MAXIMUM = "maximum"
    MINIMUM = "minimum"
    DESIGNED = "designed"
    SUPPORTED = "supported"
    OFFICIAL_NAME = "official_name"
    DESCRIPTION = "description"
    UNKNOWN = "unknown"


class SpecificationScopeType(StableStrEnum):
    PRODUCT = "product"
    SKU = "sku"
    PRODUCT_FAMILY = "product_family"
    SERVICE_TIER = "service_tier"
    REGION = "region"
    ZONE = "zone"
    SLA = "sla"
    UNKNOWN = "unknown"


class NormalizationRuleType(StableStrEnum):
    FIELD_MAPPING = "field_mapping"
    UNIT_CONVERSION = "unit_conversion"
    QUALIFIER_INFERENCE = "qualifier_inference"
    SCOPE_INFERENCE = "scope_inference"
    QUALITY_SCORING = "quality_scoring"


class NormalizationRunStatus(StableStrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ComparabilityStatus(StableStrEnum):
    COMPARABLE = "comparable"
    PARTIAL = "partial"
    NOT_COMPARABLE = "not_comparable"
    NEEDS_REVIEW = "needs_review"


class MappingLevel(StableStrEnum):
    CATEGORY = "category"
    PRODUCT = "product"
    PRODUCT_FAMILY = "product_family"
    SKU = "sku"
    SERVICE_TIER = "service_tier"
    FEATURE = "feature"
    REGION_CANDIDATE = "region_candidate"
    SCENARIO_CANDIDATE = "scenario_candidate"
    SCENARIO = "scenario"


class MappingStatus(StableStrEnum):
    EXACT = "exact"
    COMPARABLE = "comparable"
    PARTIAL = "partial"
    NONE = "none"
    PENDING_REVIEW = "pending_review"


class MappingCandidateStatus(StableStrEnum):
    CANDIDATE = "candidate"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    NOT_COMPARABLE = "not_comparable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class MappingRelationshipType(StableStrEnum):
    EQUIVALENT_CATEGORY = "equivalent_category"
    SAME_SERVICE_CLASS = "same_service_class"
    CLOSE_ALTERNATIVE = "close_alternative"
    PARTIAL_OVERLAP = "partial_overlap"
    MIGRATION_TARGET_CANDIDATE = "migration_target_candidate"
    FEATURE_OVERLAP = "feature_overlap"
    NO_DIRECT_EQUIVALENT = "no_direct_equivalent"
    DEPRECATED_REPLACEMENT_CANDIDATE = "deprecated_replacement_candidate"
    UNKNOWN = "unknown"


class MappingEvidenceRole(StableStrEnum):
    SOURCE_FIELD = "source_field"
    TARGET_FIELD = "target_field"
    CATEGORY_POSITIONING = "category_positioning"
    AVAILABILITY = "availability"
    EXCLUSION = "exclusion"
    LIFECYCLE = "lifecycle"
    SLA_CONTEXT = "sla_context"


class FieldComparisonStatus(StableStrEnum):
    MATCH = "match"
    CLOSE = "close"
    DIFFERENT = "different"
    MISSING_SOURCE = "missing_source"
    MISSING_TARGET = "missing_target"
    QUALITATIVE_ONLY = "qualitative_only"
    NOT_COMPARABLE = "not_comparable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RuleSetStatus(StableStrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DRAFT = "draft"


class EvidenceReliabilityLevel(StableStrEnum):
    OFFICIAL_STRUCTURED = "official_structured"
    OFFICIAL_SPECIFICATION = "official_specification"
    OFFICIAL_DOCUMENTATION = "official_documentation"
    OFFICIAL_SLA = "official_sla"
    OFFICIAL_PRODUCT_PAGE = "official_product_page"
    OFFICIAL_FAQ = "official_faq"
    OFFICIAL_RELEASE_NOTE = "official_release_note"
    OFFICIAL_HISTORICAL = "official_historical"
    MANUAL_IMPORT_OFFICIAL = "manual_import_official"
    THIRD_PARTY = "third_party"
    SYNTHETIC = "synthetic"
    FIXTURE = "fixture"
    UNKNOWN = "unknown"


class EvidenceStatus(StableStrEnum):
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"
    UNVERIFIABLE = "unverifiable"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"


class FreshnessStatus(StableStrEnum):
    FRESH = "fresh"
    DUE_SOON = "due_soon"
    STALE = "stale"
    UNKNOWN = "unknown"
    HISTORICAL = "historical"


class EvidencePackageType(StableStrEnum):
    PRODUCT_COMPARISON = "product_comparison"
    PRODUCT_FAMILY_COMPARISON = "product_family_comparison"
    SKU_COMPARISON = "sku_comparison"
    SERVICE_TIER_COMPARISON = "service_tier_comparison"
    FIELD_COMPARISON = "field_comparison"
    MAPPING_REVIEW = "mapping_review"
    SLA_CONTEXT = "sla_context"
    AVAILABILITY_CONTEXT = "availability_context"


class EvidenceOutputLevel(StableStrEnum):
    INTERNAL_RAW = "internal_raw"
    INTERNAL_REVIEWED = "internal_reviewed"
    CUSTOMER_ELIGIBLE = "customer_eligible"
    HISTORICAL = "historical"


class EvidencePackageRunStatus(StableStrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class BillingMode(StableStrEnum):
    ON_DEMAND = "on_demand"
    SUBSCRIPTION = "subscription"
    RESERVED = "reserved"
    SAVINGS_PLAN = "savings_plan"
    SPOT = "spot"
    TIERED = "tiered"
    REQUEST_BASED = "request_based"
    TRAFFIC_BASED = "traffic_based"
    UNKNOWN = "unknown"


class ChargeCategory(StableStrEnum):
    COMPUTE = "compute"
    STORAGE = "storage"
    REQUEST = "request"
    TRAFFIC = "traffic"
    LICENSE = "license"
    SUPPORT = "support"
    UNKNOWN = "unknown"


class DiscountType(StableStrEnum):
    LIST = "list"
    PROMOTIONAL = "promotional"
    CONTRACT = "contract"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ClaimType(StableStrEnum):
    STRENGTH = "strength"
    LIMITATION = "limitation"
    COST_RISK = "cost_risk"
    MIGRATION_RISK = "migration_risk"
    AVAILABILITY_RISK = "availability_risk"
    OPERATIONAL_ADVANTAGE = "operational_advantage"
    ECOSYSTEM_ADVANTAGE = "ecosystem_advantage"
    NEUTRAL_DIFFERENCE = "neutral_difference"


class DataType(StableStrEnum):
    NUMERIC = "numeric"
    TEXT = "text"
    BOOLEAN = "boolean"
    ENUM = "enum"


class AliasType(StableStrEnum):
    CHINESE_NAME = "chinese_name"
    ENGLISH_NAME = "english_name"
    ABBREVIATION = "abbreviation"
    HISTORICAL_NAME = "historical_name"
    SALES_NAME = "sales_name"
    OTHER = "other"


class EvidenceType(StableStrEnum):
    HTML_SECTION = "html_section"
    PDF_PAGE = "pdf_page"
    JSON_PATH = "json_path"
    API_FIELD = "api_field"
    HUMAN_NOTE = "human_note"
    UNKNOWN = "unknown"


class SKUStatus(StableStrEnum):
    ACTIVE = "active"
    PREVIEW = "preview"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class EvaluationCaseType(StableStrEnum):
    PRODUCT_MAPPING = "product_mapping"
    AVAILABILITY = "availability"
    PRICING = "pricing"
    CLAIM_GROUNDING = "claim_grounding"
    UNKNOWN = "unknown"


class IngestionRunStatus(StableStrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    UNCHANGED = "unchanged"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class IngestionRunType(StableStrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    DRY_RUN = "dry_run"
    VALIDATION = "validation"


class IngestionErrorCode(StableStrEnum):
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    DNS_FAILURE = "dns_failure"
    SSL_FAILURE = "ssl_failure"
    REDIRECT_VIOLATION = "redirect_violation"
    MIME_MISMATCH = "mime_mismatch"
    FILE_TOO_LARGE = "file_too_large"
    DOMAIN_NOT_ALLOWED = "domain_not_allowed"
    REQUIRES_BROWSER = "requires_browser"
    REQUIRES_AUTHENTICATION = "requires_authentication"
    EMPTY_CONTENT = "empty_content"
    DUPLICATE_CONTENT = "duplicate_content"
    STORAGE_FAILURE = "storage_failure"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


class ChangeStatus(StableStrEnum):
    FIRST_SEEN = "first_seen"
    UNCHANGED = "unchanged"
    CONTENT_CHANGED = "content_changed"
    METADATA_CHANGED = "metadata_changed"
    REDIRECT_CHANGED = "redirect_changed"
    CONTENT_TYPE_CHANGED = "content_type_changed"
    UNAVAILABLE = "unavailable"
    RESTORED = "restored"
    UNKNOWN = "unknown"


class ComplianceReviewStatus(StableStrEnum):
    APPROVED = "approved"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    DISALLOWED = "disallowed"
    UNKNOWN = "unknown"


class ParserRunStatus(StableStrEnum):
    SUCCEEDED = "succeeded"
    UNCHANGED = "unchanged"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class ReviewItemStatus(StableStrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class ReviewItemType(StableStrEnum):
    LOW_CONFIDENCE_FIELD = "low_confidence_field"
    CONFLICTING_OFFICIAL_SOURCE = "conflicting_official_source"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    UNSUPPORTED_TABLE = "unsupported_table"
    QUALITY_ISSUE = "quality_issue"


class QualityIssueSeverity(StableStrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProductFamilyType(StableStrEnum):
    ECS_INSTANCE_FAMILY = "ecs_instance_family"
    OBS_STORAGE_CLASS = "obs_storage_class"
    AWS_EC2_INSTANCE_FAMILY = "aws_ec2_instance_family"
    AWS_S3_STORAGE_CLASS = "aws_s3_storage_class"
    ALIYUN_ECS_INSTANCE_FAMILY = "aliyun_ecs_instance_family"
    ALIYUN_OSS_STORAGE_CLASS = "aliyun_oss_storage_class"


class SLARecordType(StableStrEnum):
    AVAILABILITY = "availability"
    DURABILITY = "durability"
    SERVICE_CREDIT = "service_credit"
    OTHER = "other"


def sql_in_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)
