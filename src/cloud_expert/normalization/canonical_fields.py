from dataclasses import dataclass

from cloud_expert.database.enums import (
    CanonicalDomain,
    DataType,
    SpecificationScopeType,
    ValueQualifier,
)
from cloud_expert.ingestion.providers.aliyun.ecs.mappings import ALIYUN_ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aliyun.oss.mappings import ALIYUN_OSS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.ec2.mappings import EC2_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.s3.mappings import S3_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.ecs.mappings import ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.obs.mappings import OBS_SPEC_DEFINITIONS


@dataclass(frozen=True)
class CanonicalFieldSeed:
    code: str
    name: str
    domain: str
    data_type: str
    canonical_unit: str | None
    unit_dimension: str | None
    default_qualifier: str
    default_scope_type: str
    description: str
    is_comparable: bool = True


@dataclass(frozen=True)
class LegacyFieldMapping:
    source_field_code: str
    canonical_field_code: str
    value_qualifier: str
    scope_type: str
    source_unit: str | None = None
    canonical_unit: str | None = None
    conversion_note: str | None = None

    @property
    def rule_code(self) -> str:
        return f"legacy.{self.source_field_code}.to.{self.canonical_field_code}"


CANONICAL_FIELD_SEEDS: tuple[CanonicalFieldSeed, ...] = (
    CanonicalFieldSeed(
        "compute.cpu.vcpu_count",
        "vCPU count",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "count",
        "count",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Provider-published virtual CPU count for an instance SKU.",
    ),
    CanonicalFieldSeed(
        "compute.memory.capacity_gib",
        "Memory capacity",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "GiB",
        "digital_storage_binary",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Provider-published memory capacity normalized to GiB.",
    ),
    CanonicalFieldSeed(
        "compute.cpu.architecture",
        "CPU architecture",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "CPU architecture text such as x86_64 or arm64 when officially stated.",
    ),
    CanonicalFieldSeed(
        "compute.cpu.processor_vendor",
        "Processor vendor",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Official processor vendor or inferred vendor token from an official table.",
    ),
    CanonicalFieldSeed(
        "compute.cpu.processor_model",
        "Processor model",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Official processor model or raw processor description.",
    ),
    CanonicalFieldSeed(
        "compute.network.bandwidth_gbps",
        "Network bandwidth",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "Gbps",
        "network_bandwidth_decimal",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        "Network bandwidth normalized to Gbps; qualifier differentiates baseline and maximum.",
    ),
    CanonicalFieldSeed(
        "compute.network.packets_per_second",
        "Network packets per second",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "PPS",
        "packet_rate_decimal",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        "Packet processing limit normalized to packets per second.",
    ),
    CanonicalFieldSeed(
        "compute.network.connections",
        "Network connections",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "count",
        "count",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        "Maximum connection count when provided by official instance specifications.",
    ),
    CanonicalFieldSeed(
        "compute.network.ena_express_supported",
        "ENA Express supported",
        CanonicalDomain.COMPUTE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SKU.value,
        "Whether AWS ENA Express or a comparable provider-published network acceleration feature is supported.",
    ),
    CanonicalFieldSeed(
        "compute.block_storage.bandwidth_gbps",
        "Block storage bandwidth",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "Gbps",
        "network_bandwidth_decimal",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        "Attached block storage or cloud disk bandwidth normalized to Gbps.",
    ),
    CanonicalFieldSeed(
        "compute.block_storage.iops",
        "Block storage IOPS",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "IOPS",
        "operations_per_second",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        "Attached block storage or cloud disk I/O operations per second.",
    ),
    CanonicalFieldSeed(
        "compute.storage.local_disk_count",
        "Local disk count",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "count",
        "count",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Number of local disks attached to the instance SKU.",
    ),
    CanonicalFieldSeed(
        "compute.storage.local_capacity_gib",
        "Local storage capacity",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "GiB",
        "digital_storage_binary",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Local storage capacity normalized to GiB.",
    ),
    CanonicalFieldSeed(
        "compute.storage.local_type",
        "Local storage type",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Official local disk media or storage type text.",
    ),
    CanonicalFieldSeed(
        "compute.accelerator.gpu_count",
        "GPU count",
        CanonicalDomain.COMPUTE.value,
        DataType.NUMERIC.value,
        "count",
        "count",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "GPU accelerator count for a compute SKU.",
    ),
    CanonicalFieldSeed(
        "compute.accelerator.gpu_model",
        "GPU model",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Official GPU accelerator model text.",
    ),
    CanonicalFieldSeed(
        "compute.system.virtualization_type",
        "Virtualization type",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        "Virtualization type text when exposed by official specifications.",
    ),
    CanonicalFieldSeed(
        "compute.system.supported_os_family",
        "Supported operating system family",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SKU.value,
        "Supported operating system family text from official sources.",
    ),
    CanonicalFieldSeed(
        "compute.instance.family_level",
        "Instance family level",
        CanonicalDomain.COMPUTE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.PRODUCT_FAMILY.value,
        "Provider family-level label such as enterprise or shared-basic class.",
    ),
    CanonicalFieldSeed(
        "object_storage.reliability.durability_percentage",
        "Durability percentage",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.NUMERIC.value,
        "percent",
        "percentage",
        ValueQualifier.DESIGNED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Published object durability target or design value.",
    ),
    CanonicalFieldSeed(
        "object_storage.reliability.availability_percentage",
        "Availability percentage",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.NUMERIC.value,
        "percent",
        "percentage",
        ValueQualifier.DESIGNED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Published service availability target or SLA-like percentage.",
    ),
    CanonicalFieldSeed(
        "object_storage.limits.max_object_size_gib",
        "Maximum object size",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.NUMERIC.value,
        "GiB",
        "digital_storage_binary",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Maximum object size normalized to GiB.",
    ),
    CanonicalFieldSeed(
        "object_storage.limits.max_single_upload_size_gib",
        "Maximum single upload size",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.NUMERIC.value,
        "GiB",
        "digital_storage_binary",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Maximum single-operation upload size normalized to GiB.",
    ),
    CanonicalFieldSeed(
        "object_storage.billing.minimum_billable_object_size_kib",
        "Minimum billable object size",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.NUMERIC.value,
        "KiB",
        "digital_storage_binary",
        ValueQualifier.MINIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Minimum object size charged for billing purposes, normalized to KiB.",
    ),
    CanonicalFieldSeed(
        "object_storage.billing.minimum_storage_duration_days",
        "Minimum storage duration",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.NUMERIC.value,
        "day",
        "duration_day",
        ValueQualifier.MINIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Minimum billable or recommended storage duration in days.",
    ),
    CanonicalFieldSeed(
        "object_storage.retrieval.time_description",
        "Retrieval time description",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Provider wording for storage-class retrieval characteristics.",
    ),
    CanonicalFieldSeed(
        "object_storage.redundancy.type",
        "Redundancy type",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.TEXT.value,
        None,
        None,
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Redundancy type or zone redundancy wording.",
    ),
    CanonicalFieldSeed(
        "object_storage.capability.multipart_upload_supported",
        "Multipart upload supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether multipart upload is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.capability.versioning_supported",
        "Versioning supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether object versioning is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.capability.lifecycle_management_supported",
        "Lifecycle management supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether lifecycle management rules are supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.data_protection.cross_region_replication_supported",
        "Cross-region replication supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether cross-region replication is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.security.server_side_encryption_supported",
        "Server-side encryption supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether provider-managed server-side encryption is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.security.customer_managed_key_supported",
        "Customer-managed key supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether customer-managed keys are supported for encryption.",
    ),
    CanonicalFieldSeed(
        "object_storage.website.static_hosting_supported",
        "Static website hosting supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether static website hosting is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.integration.event_notification_supported",
        "Event notification supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether event notification integration is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.data_protection.object_lock_supported",
        "Object lock supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether immutable object lock or WORM-style capability is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.performance.transfer_acceleration_supported",
        "Transfer acceleration supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether transfer acceleration is supported.",
    ),
    CanonicalFieldSeed(
        "object_storage.endpoint.dual_stack_supported",
        "Dual-stack endpoint supported",
        CanonicalDomain.OBJECT_STORAGE.value,
        DataType.BOOLEAN.value,
        None,
        None,
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        "Whether IPv4/IPv6 dual-stack endpoints are supported.",
    ),
)


LEGACY_FIELD_MAPPINGS: tuple[LegacyFieldMapping, ...] = (
    LegacyFieldMapping(
        "compute.vcpu_count",
        "compute.cpu.vcpu_count",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="count",
    ),
    LegacyFieldMapping(
        "compute.memory_gib",
        "compute.memory.capacity_gib",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="GiB",
    ),
    LegacyFieldMapping(
        "compute.cpu_architecture",
        "compute.cpu.architecture",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "compute.processor_vendor",
        "compute.cpu.processor_vendor",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "compute.processor_model",
        "compute.cpu.processor_model",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "network.baseline_bandwidth_gbps",
        "compute.network.bandwidth_gbps",
        ValueQualifier.BASELINE.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="Gbps",
    ),
    LegacyFieldMapping(
        "network.max_bandwidth_gbps",
        "compute.network.bandwidth_gbps",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="Gbps",
    ),
    LegacyFieldMapping(
        "network.ebs_bandwidth_gbps",
        "compute.block_storage.bandwidth_gbps",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="Gbps",
    ),
    LegacyFieldMapping(
        "network.cloud_disk_bandwidth_gbps",
        "compute.block_storage.bandwidth_gbps",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="Gbps",
    ),
    LegacyFieldMapping(
        "network.max_pps",
        "compute.network.packets_per_second",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="PPS",
        conversion_note="Legacy Huawei definitions may use 10k PPS units.",
    ),
    LegacyFieldMapping(
        "network.max_connections",
        "compute.network.connections",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="count",
    ),
    LegacyFieldMapping(
        "network.ena_express_supported",
        "compute.network.ena_express_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "storage.cloud_disk_iops",
        "compute.block_storage.iops",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="IOPS",
    ),
    LegacyFieldMapping(
        "storage.local_disk_count",
        "compute.storage.local_disk_count",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="count",
    ),
    LegacyFieldMapping(
        "storage.local_disk_capacity_gib",
        "compute.storage.local_capacity_gib",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="GiB",
    ),
    LegacyFieldMapping(
        "storage.local_disk_type",
        "compute.storage.local_type",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "gpu.count",
        "compute.accelerator.gpu_count",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
        canonical_unit="count",
    ),
    LegacyFieldMapping(
        "gpu.model",
        "compute.accelerator.gpu_model",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "system.virtualization_type",
        "compute.system.virtualization_type",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "system.supported_os_family",
        "compute.system.supported_os_family",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SKU.value,
    ),
    LegacyFieldMapping(
        "system.instance_family_level",
        "compute.instance.family_level",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.PRODUCT_FAMILY.value,
    ),
    LegacyFieldMapping(
        "object_storage.durability_percentage",
        "object_storage.reliability.durability_percentage",
        ValueQualifier.DESIGNED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        canonical_unit="percent",
    ),
    LegacyFieldMapping(
        "object_storage.availability_percentage",
        "object_storage.reliability.availability_percentage",
        ValueQualifier.DESIGNED.value,
        SpecificationScopeType.SERVICE_TIER.value,
        canonical_unit="percent",
    ),
    LegacyFieldMapping(
        "object_storage.max_object_size_gib",
        "object_storage.limits.max_object_size_gib",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        canonical_unit="GiB",
    ),
    LegacyFieldMapping(
        "object_storage.max_single_upload_size_gib",
        "object_storage.limits.max_single_upload_size_gib",
        ValueQualifier.MAXIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        canonical_unit="GiB",
    ),
    LegacyFieldMapping(
        "object_storage.minimum_billable_object_size_kib",
        "object_storage.billing.minimum_billable_object_size_kib",
        ValueQualifier.MINIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        canonical_unit="KiB",
    ),
    LegacyFieldMapping(
        "object_storage.minimum_storage_duration_days",
        "object_storage.billing.minimum_storage_duration_days",
        ValueQualifier.MINIMUM.value,
        SpecificationScopeType.SERVICE_TIER.value,
        canonical_unit="day",
    ),
    LegacyFieldMapping(
        "object_storage.retrieval_time_description",
        "object_storage.retrieval.time_description",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.redundancy_type",
        "object_storage.redundancy.type",
        ValueQualifier.EXACT.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.multipart_upload_supported",
        "object_storage.capability.multipart_upload_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.versioning_supported",
        "object_storage.capability.versioning_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.lifecycle_management_supported",
        "object_storage.capability.lifecycle_management_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.cross_region_replication_supported",
        "object_storage.data_protection.cross_region_replication_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.server_side_encryption_supported",
        "object_storage.security.server_side_encryption_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.customer_managed_key_supported",
        "object_storage.security.customer_managed_key_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.static_website_hosting_supported",
        "object_storage.website.static_hosting_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.event_notification_supported",
        "object_storage.integration.event_notification_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.object_lock_supported",
        "object_storage.data_protection.object_lock_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.transfer_acceleration_supported",
        "object_storage.performance.transfer_acceleration_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
    LegacyFieldMapping(
        "object_storage.dual_stack_endpoint_supported",
        "object_storage.endpoint.dual_stack_supported",
        ValueQualifier.SUPPORTED.value,
        SpecificationScopeType.SERVICE_TIER.value,
    ),
)


def known_legacy_spec_fields() -> set[str]:
    return (
        set(ECS_SPEC_DEFINITIONS)
        | set(OBS_SPEC_DEFINITIONS)
        | set(EC2_SPEC_DEFINITIONS)
        | set(S3_SPEC_DEFINITIONS)
        | set(ALIYUN_ECS_SPEC_DEFINITIONS)
        | set(ALIYUN_OSS_SPEC_DEFINITIONS)
    )


def canonical_seed_by_code() -> dict[str, CanonicalFieldSeed]:
    return {seed.code: seed for seed in CANONICAL_FIELD_SEEDS}


def legacy_mapping_by_source_field() -> dict[str, LegacyFieldMapping]:
    return {mapping.source_field_code: mapping for mapping in LEGACY_FIELD_MAPPINGS}


def validate_canonical_registry() -> list[str]:
    errors: list[str] = []
    seed_codes = [seed.code for seed in CANONICAL_FIELD_SEEDS]
    duplicate_seed_codes = sorted({code for code in seed_codes if seed_codes.count(code) > 1})
    errors.extend(f"Duplicate canonical field definition: {code}" for code in duplicate_seed_codes)

    canonical_codes = set(seed_codes)
    mapping_sources = [mapping.source_field_code for mapping in LEGACY_FIELD_MAPPINGS]
    duplicate_sources = sorted(
        {source for source in mapping_sources if mapping_sources.count(source) > 1}
    )
    errors.extend(f"Duplicate legacy field mapping: {source}" for source in duplicate_sources)

    known_legacy_fields = known_legacy_spec_fields()
    for mapping in LEGACY_FIELD_MAPPINGS:
        if mapping.canonical_field_code not in canonical_codes:
            errors.append(
                f"Mapping target does not exist: {mapping.source_field_code} -> "
                f"{mapping.canonical_field_code}"
            )
        if mapping.source_field_code not in known_legacy_fields:
            errors.append(f"Mapping source is not registered by current parsers: {mapping.source_field_code}")

    unmapped = sorted(known_legacy_fields - set(mapping_sources))
    errors.extend(f"Legacy specification field has no canonical mapping: {code}" for code in unmapped)
    return errors
