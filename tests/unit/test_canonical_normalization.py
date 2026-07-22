from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import DataType, ReviewStatus
from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.normalization.canonical_fields import validate_canonical_registry
from cloud_expert.normalization.canonical_service import (
    normalize_specifications,
    seed_canonical_registry,
)
from cloud_expert.normalization.unit_standardization import standardize_value
from tests.fixtures.synthetic_data import load_synthetic_fixture


def test_canonical_registry_is_complete() -> None:
    assert validate_canonical_registry() == []


def test_packet_rate_standardization_converts_10k_pps() -> None:
    value = standardize_value(
        data_type=DataType.NUMERIC.value,
        raw_value="12",
        numeric_value=Decimal("12"),
        text_value=None,
        boolean_value=None,
        raw_unit="10k PPS",
        source_canonical_unit="10k PPS",
        target_unit="PPS",
    )
    assert value.numeric_value == Decimal("120000")
    assert value.canonical_unit == "PPS"
    assert value.requires_review is False


def test_normalize_specifications_is_idempotent(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
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

    seed_summary = seed_canonical_registry(session)
    assert seed_summary.fields_created > 0

    first = normalize_specifications(
        session,
        provider_code="synthetic_huawei",
        product_code="synthetic_compute_a",
        run_key="synthetic_run",
    )
    assert first.records_created == 1
    assert first.records_skipped == 1

    second = normalize_specifications(
        session,
        provider_code="synthetic_huawei",
        product_code="synthetic_compute_a",
        run_key="synthetic_run",
    )
    assert second.records_created == 0
    assert second.records_updated == 1

    count = session.scalar(select(func.count()).select_from(NormalizedSpecification))
    normalized = session.scalar(select(NormalizedSpecification))
    assert count == 1
    assert normalized is not None
    assert normalized.canonical_value == "4"
    assert normalized.scope_type == "sku"
    assert normalized.value_qualifier == "exact"
    assert normalized.review_status == ReviewStatus.MACHINE_EXTRACTED.value
