from cloud_expert.ingestion.providers.huawei_cloud.source_catalog import (
    HUAWEI_SOURCE_EXPECTATIONS,
    HuaweiSourceExpectation,
)
from cloud_expert.ingestion.registry.validator import summarize_validation, validate_registry
from cloud_expert.quality.coverage import calculate_coverage, expected_fields_for_product

VALID_SOURCE_YAML = """
source_id: synthetic_source
provider_code: synthetic_provider
market_mode: domestic
product_code: synthetic_product
source_type: documentation
title: Synthetic Source
authority_level: unknown
url: https://example.invalid/synthetic
enabled: {enabled}
expected_content_type:
  - text/html
domain_policy:
  allowed_domains:
    - example.invalid
terms_review_status: approved
"""


def test_registry_validator_reports_duplicates_disabled_and_bad_files(tmp_path) -> None:
    (tmp_path / "valid_a.yaml").write_text(
        VALID_SOURCE_YAML.format(enabled="true"),
        encoding="utf-8",
    )
    (tmp_path / "valid_b.yaml").write_text(
        VALID_SOURCE_YAML.format(enabled="false"),
        encoding="utf-8",
    )
    (tmp_path / "bad.yaml").write_text("[]", encoding="utf-8")

    results = validate_registry(tmp_path)
    summary = summarize_validation(results)

    assert summary["total_sources"] == 3
    assert summary["valid_sources"] == 0
    assert summary["disabled_sources"] == 1
    assert summary["configuration_errors"] == 3
    assert summary["duplicate_source_ids"] == 1
    assert any(result.warnings == ["source disabled"] for result in results)


def test_quality_coverage_handles_all_first_six_week_products() -> None:
    assert calculate_coverage("unknown", {"field"}).coverage_ratio == 1.0
    assert expected_fields_for_product("ecs")
    assert expected_fields_for_product("obs")
    assert expected_fields_for_product("ec2")
    assert expected_fields_for_product("s3")
    assert expected_fields_for_product("ecs", "aliyun")
    assert expected_fields_for_product("oss", "aliyun")

    ecs_fields = {"compute.vcpu_count", "product.official_name"}
    coverage = calculate_coverage("ecs", ecs_fields)
    assert coverage.observed_fields == 2
    assert 0 < coverage.coverage_ratio < 1


def test_huawei_source_catalog_is_structured() -> None:
    expectation = HUAWEI_SOURCE_EXPECTATIONS["huawei_cloud_ecs_general_entry_specs"]
    assert isinstance(expectation, HuaweiSourceExpectation)
    assert expectation.product_code == "ecs"
    assert "compute.vcpu_count" in expectation.expected_fields
