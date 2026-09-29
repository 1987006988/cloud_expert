ALIYUN_PROVIDER_CODE = "aliyun"
ALIYUN_PUBLIC_CN_PARTITION = "aliyun_public_cn"
PARSER_VERSION = "2026.08.week11_review_remediation_v1"


def parser_version_for_product(product_code: str | None) -> str:
    """Select the ECS parser's version without relabeling OSS or legacy scopes."""
    if product_code == "ecs":
        # Import on demand: the ECS parser also imports this provider module.
        from cloud_expert.ingestion.providers.aliyun.ecs.parser import PARSER_VERSION as ecs_version

        return ecs_version
    return PARSER_VERSION


ALIYUN_PROVIDER_PROFILE = {
    "code": ALIYUN_PROVIDER_CODE,
    "name": "Alibaba Cloud China Public Cloud",
    "display_name": "Alibaba Cloud",
    "provider_type": "cloud",
    "official_website": "https://www.aliyun.com/",
}

ALIYUN_PUBLIC_CN_PARTITION_PROFILE = {
    "partition_code": ALIYUN_PUBLIC_CN_PARTITION,
    "partition_name": "Alibaba Cloud Public China",
    "market_mode": "domestic",
    "geography_scope": "Chinese mainland public cloud",
}


def is_mainland_region_code(region_code: str) -> bool:
    final_segment = region_code.rsplit("-", 1)[-1]
    return (
        region_code.startswith("cn-")
        and region_code != "cn-hongkong"
        and not (len(final_segment) == 1 and final_segment.isalpha())
        and "-gov-" not in region_code
        and not region_code.startswith("cn-north-2-gov")
    )
