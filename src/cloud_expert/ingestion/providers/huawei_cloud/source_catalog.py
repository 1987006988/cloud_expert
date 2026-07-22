from dataclasses import dataclass


@dataclass(frozen=True)
class HuaweiSourceExpectation:
    source_id: str
    product_code: str
    expected_fields: tuple[str, ...]
    parser_name: str


HUAWEI_SOURCE_EXPECTATIONS = {
    "huawei_cloud_ecs_product_page": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_product_page",
        product_code="ecs",
        expected_fields=("product.official_name", "product.description"),
        parser_name="huawei_cloud_ecs_product",
    ),
    "huawei_cloud_ecs_documentation_intro": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_documentation_intro",
        product_code="ecs",
        expected_fields=("product.official_name", "product.description"),
        parser_name="huawei_cloud_ecs_product",
    ),
    "huawei_cloud_ecs_product_features": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_product_features",
        product_code="ecs",
        expected_fields=("product.description",),
        parser_name="huawei_cloud_ecs_product",
    ),
    "huawei_cloud_ecs_instance_types": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_instance_types",
        product_code="ecs",
        expected_fields=("compute.cpu_architecture", "ecs.instance_family"),
        parser_name="huawei_cloud_ecs_instance",
    ),
    "huawei_cloud_ecs_general_entry_specs": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_general_entry_specs",
        product_code="ecs",
        expected_fields=("compute.vcpu_count", "compute.memory_gib", "network.max_bandwidth_gbps"),
        parser_name="huawei_cloud_ecs_specs",
    ),
    "huawei_cloud_ecs_high_performance_specs": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_high_performance_specs",
        product_code="ecs",
        expected_fields=("compute.vcpu_count", "compute.memory_gib", "network.max_bandwidth_gbps"),
        parser_name="huawei_cloud_ecs_specs",
    ),
    "huawei_cloud_ecs_regions": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_regions",
        product_code="ecs",
        expected_fields=("region.availability",),
        parser_name="huawei_cloud_ecs_regions",
    ),
    "huawei_cloud_ecs_quotas_limits": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_quotas_limits",
        product_code="ecs",
        expected_fields=("product.limitations",),
        parser_name="huawei_cloud_ecs_limits",
    ),
    "huawei_cloud_ecs_sla": HuaweiSourceExpectation(
        source_id="huawei_cloud_ecs_sla",
        product_code="ecs",
        expected_fields=("sla.availability_percentage",),
        parser_name="huawei_cloud_ecs_sla",
    ),
    "huawei_cloud_obs_product_page": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_product_page",
        product_code="obs",
        expected_fields=("product.official_name", "product.description"),
        parser_name="huawei_cloud_obs_product",
    ),
    "huawei_cloud_obs_features_page": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_features_page",
        product_code="obs",
        expected_fields=("object_storage.lifecycle_management_supported",),
        parser_name="huawei_cloud_obs_features",
    ),
    "huawei_cloud_obs_documentation_intro": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_documentation_intro",
        product_code="obs",
        expected_fields=("product.official_name", "product.description"),
        parser_name="huawei_cloud_obs_intro",
    ),
    "huawei_cloud_obs_product_features": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_product_features",
        product_code="obs",
        expected_fields=(
            "object_storage.versioning_supported",
            "object_storage.lifecycle_management_supported",
        ),
        parser_name="huawei_cloud_obs_features",
    ),
    "huawei_cloud_obs_storage_classes": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_storage_classes",
        product_code="obs",
        expected_fields=(
            "object_storage.minimum_storage_duration_days",
            "object_storage.durability_percentage",
            "object_storage.availability_percentage",
        ),
        parser_name="huawei_cloud_obs_storage_classes",
    ),
    "huawei_cloud_obs_constraints_limits": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_constraints_limits",
        product_code="obs",
        expected_fields=("object_storage.max_object_size_gib",),
        parser_name="huawei_cloud_obs_limits",
    ),
    "huawei_cloud_obs_regions": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_regions",
        product_code="obs",
        expected_fields=("region.availability",),
        parser_name="huawei_cloud_obs_regions",
    ),
    "huawei_cloud_obs_lifecycle": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_lifecycle",
        product_code="obs",
        expected_fields=("object_storage.lifecycle_management_supported",),
        parser_name="huawei_cloud_obs_features",
    ),
    "huawei_cloud_obs_versioning": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_versioning",
        product_code="obs",
        expected_fields=("object_storage.versioning_supported",),
        parser_name="huawei_cloud_obs_features",
    ),
    "huawei_cloud_obs_cross_region_replication": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_cross_region_replication",
        product_code="obs",
        expected_fields=("object_storage.cross_region_replication_supported",),
        parser_name="huawei_cloud_obs_features",
    ),
    "huawei_cloud_obs_server_side_encryption": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_server_side_encryption",
        product_code="obs",
        expected_fields=("object_storage.server_side_encryption_supported",),
        parser_name="huawei_cloud_obs_features",
    ),
    "huawei_cloud_obs_sla": HuaweiSourceExpectation(
        source_id="huawei_cloud_obs_sla",
        product_code="obs",
        expected_fields=("sla.availability_percentage",),
        parser_name="huawei_cloud_obs_sla",
    ),
}
