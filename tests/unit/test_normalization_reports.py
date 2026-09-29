from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from cloud_expert.database.enums import CanonicalDomain, DataType
from cloud_expert.database.models.product import SKU, Product, ProductCategory
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.normalization.canonical_fields import LEGACY_FIELD_MAPPINGS
from cloud_expert.normalization.canonical_service import (
    normalize_specifications,
    seed_canonical_registry,
)
from cloud_expert.normalization.reports import (
    FIELD_MATRIX_HEADERS,
    build_cross_provider_coverage_report,
    build_field_matrix_rows,
    build_normalization_quality_report,
    write_coverage_markdown,
    write_markdown_table,
)
from tests.fixtures.synthetic_data import load_synthetic_fixture


def test_field_matrix_rows_include_stage2_status_columns(tmp_path: Path) -> None:
    rows = build_field_matrix_rows(CanonicalDomain.COMPUTE.value)
    assert rows
    assert set(FIELD_MATRIX_HEADERS).issubset(rows[0])
    assert {row["unit_status"] for row in rows} <= {
        "canonical_unit_defined",
        "unit_not_applicable",
        "unit_review_required",
    }
    assert any(row["qualifier_status"] == "explicit_mapping_qualifier" for row in rows)

    output = tmp_path / "matrix.md"
    write_markdown_table(rows[:2], output, title="Synthetic Matrix")
    content = output.read_text(encoding="utf-8")
    assert "semantic_group" in content
    assert "comparability_status" in content


def test_normalization_reports_summarize_seeded_and_normalized_data(
    session: Session,
    tmp_path: Path,
) -> None:
    fixture = load_synthetic_fixture(session)
    assert isinstance(fixture["category"], ProductCategory)
    assert isinstance(fixture["product"], Product)
    assert isinstance(fixture["sku"], SKU)
    assert isinstance(fixture["evidence"], Evidence)
    definition = SpecificationDefinition(
        code="compute.vcpu_count",
        name="vCPU count",
        category_id=fixture["category"].id,
        data_type=DataType.NUMERIC.value,
        canonical_unit="count",
        is_required=False,
    )
    session.add(definition)
    session.flush()
    session.add(
        ProductSpecification(
            product_id=fixture["product"].id,
            sku_id=fixture["sku"].id,
            definition_id=definition.id,
            numeric_value=Decimal("4"),
            raw_value="4",
            raw_unit="count",
            canonical_value="4",
            canonical_unit="count",
            evidence_id=fixture["evidence"].id,
        )
    )
    session.flush()

    seed_canonical_registry(session)
    normalize_specifications(
        session,
        provider_code="synthetic_huawei",
        product_code="synthetic_compute_a",
        run_key="reports-test",
    )

    quality = build_normalization_quality_report(session)
    assert quality["canonical_field_definitions"] == 38
    assert quality["normalization_rules"] == len(LEGACY_FIELD_MAPPINGS)
    assert quality["normalized_specifications"] == 1
    assert quality["product_normalized_specification_counts"] == {
        "synthetic_huawei/synthetic_compute_a": 1
    }

    coverage = build_cross_provider_coverage_report(session)
    assert coverage["canonical_fields"] == 38
    output = tmp_path / "coverage.md"
    write_coverage_markdown(coverage, output)
    assert "Cross-Provider Canonical Coverage" in output.read_text(encoding="utf-8")
