from dataclasses import dataclass

from cloud_expert.ingestion.providers.aliyun.ecs.mappings import ALIYUN_ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aliyun.oss.mappings import ALIYUN_OSS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.ec2.mappings import EC2_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.aws.s3.mappings import S3_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.ecs.mappings import ECS_SPEC_DEFINITIONS
from cloud_expert.ingestion.providers.huawei_cloud.obs.mappings import OBS_SPEC_DEFINITIONS


@dataclass(frozen=True)
class CoverageResult:
    expected_fields: int
    observed_fields: int

    @property
    def coverage_ratio(self) -> float:
        if self.expected_fields == 0:
            return 1.0
        return self.observed_fields / self.expected_fields


def expected_fields_for_product(
    product_code: str,
    provider_code: str | None = None,
) -> set[str]:
    if provider_code == "aliyun" and product_code == "ecs":
        return set(ALIYUN_ECS_SPEC_DEFINITIONS) | {
            "product.official_name",
            "product.description",
            "ecs.instance_family",
            "sku.provider_sku_code",
            "cloud.partition",
            "region.code",
            "zone.code",
            "availability.status",
            "sla.availability_percentage",
        }
    if provider_code == "aliyun" and product_code == "oss":
        return set(ALIYUN_OSS_SPEC_DEFINITIONS) | {
            "product.official_name",
            "product.description",
            "oss.storage_class.official_name",
            "cloud.partition",
            "region.code",
            "availability.status",
            "sla.availability_percentage",
        }
    if product_code == "ecs":
        return set(ECS_SPEC_DEFINITIONS) | {
            "product.official_name",
            "product.description",
            "ecs.instance_family",
            "sku.provider_sku_code",
            "sla.availability_percentage",
        }
    if product_code == "obs":
        return set(OBS_SPEC_DEFINITIONS) | {
            "product.official_name",
            "product.description",
            "obs.storage_class.official_name",
            "sla.availability_percentage",
        }
    if product_code == "ec2":
        return set(EC2_SPEC_DEFINITIONS) | {
            "product.official_name",
            "product.description",
            "ec2.instance_family",
            "sku.provider_sku_code",
            "cloud.partition",
            "region.code",
            "availability.status",
            "sla.availability_percentage",
        }
    if product_code == "s3":
        return set(S3_SPEC_DEFINITIONS) | {
            "product.official_name",
            "product.description",
            "s3.storage_class.official_name",
            "cloud.partition",
            "region.code",
            "availability.status",
            "sla.availability_percentage",
        }
    return set()


def calculate_coverage(
    product_code: str,
    observed_fields: set[str],
    provider_code: str | None = None,
) -> CoverageResult:
    expected = expected_fields_for_product(product_code, provider_code)
    return CoverageResult(
        expected_fields=len(expected),
        observed_fields=len(expected & observed_fields),
    )
