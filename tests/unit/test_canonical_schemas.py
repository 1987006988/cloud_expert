from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from cloud_expert.database.enums import (
    CanonicalDomain,
    ComparabilityStatus,
    DataType,
    NormalizationRuleType,
    NormalizationRunStatus,
    ReviewStatus,
    SpecificationScopeType,
    ValueQualifier,
)
from cloud_expert.schemas.canonical import (
    CanonicalFieldDefinitionCreate,
    CanonicalFieldDefinitionList,
    CanonicalFieldDefinitionRead,
    CanonicalFieldDefinitionUpdate,
    ComparabilityAssessmentCreate,
    ComparabilityAssessmentList,
    NormalizationRuleCreate,
    NormalizationRuleList,
    NormalizationRunCreate,
    NormalizationRunRead,
    NormalizedSpecificationCreate,
    NormalizedSpecificationList,
)


def test_canonical_field_schema_round_trips_enums_and_metadata() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    field = CanonicalFieldDefinitionCreate(
        code="compute.synthetic.field",
        name="Synthetic Field",
        domain=CanonicalDomain.COMPUTE,
        data_type=DataType.NUMERIC,
        canonical_unit="count",
        unit_dimension="count",
        default_qualifier=ValueQualifier.EXACT,
        default_scope_type=SpecificationScopeType.SKU,
        metadata_json={"semantic_status": "defined"},
    )
    assert field.domain == CanonicalDomain.COMPUTE.value
    assert field.metadata_json == {"semantic_status": "defined"}

    update = CanonicalFieldDefinitionUpdate(is_comparable=False)
    assert update.is_comparable is False

    read = CanonicalFieldDefinitionRead(
        id=1,
        created_at=created,
        updated_at=created,
        **field.model_dump(),
    )
    listing = CanonicalFieldDefinitionList(total=1, items=[read])
    assert listing.items[0].code == "compute.synthetic.field"


def test_normalization_rule_and_run_schemas_validate_counts() -> None:
    started = datetime(2026, 1, 1, tzinfo=UTC)
    rule = NormalizationRuleCreate(
        code="synthetic.rule",
        rule_type=NormalizationRuleType.FIELD_MAPPING,
        source_field_code="compute.vcpu_count",
        canonical_field_id=1,
        value_qualifier=ValueQualifier.EXACT,
        scope_type=SpecificationScopeType.SKU,
    )
    assert rule.rule_type == NormalizationRuleType.FIELD_MAPPING.value
    assert NormalizationRuleList(total=1, items=[]).total == 1

    run = NormalizationRunCreate(
        run_key="synthetic-run",
        status=NormalizationRunStatus.SUCCEEDED,
        started_at=started,
        records_examined=2,
        records_created=1,
    )
    read = NormalizationRunRead(
        id=1,
        created_at=started,
        **run.model_dump(),
    )
    assert read.status == NormalizationRunStatus.SUCCEEDED.value

    with pytest.raises(ValidationError):
        NormalizationRunCreate(
            run_key="bad-run",
            status=NormalizationRunStatus.FAILED,
            started_at=started,
            records_examined=-1,
        )


def test_normalized_specification_requires_one_value() -> None:
    base = {
        "product_specification_id": 1,
        "product_id": 1,
        "canonical_field_id": 1,
        "normalization_rule_id": 1,
        "evidence_id": 1,
        "scope_type": SpecificationScopeType.SKU,
        "scope_identity": "synthetic-sku",
        "value_qualifier": ValueQualifier.EXACT,
        "raw_value": "4",
        "quality_score": Decimal("0.9000"),
        "review_status": ReviewStatus.PENDING_REVIEW,
        "source_value_hash": "abc123",
    }
    spec = NormalizedSpecificationCreate(**base, numeric_value=Decimal("4"))
    assert spec.numeric_value == Decimal("4")
    assert NormalizedSpecificationList(total=1, items=[]).items == []

    with pytest.raises(ValidationError):
        NormalizedSpecificationCreate(
            **base,
            numeric_value=Decimal("4"),
            text_value="four",
        )
    with pytest.raises(ValidationError):
        NormalizedSpecificationCreate(**base)


def test_comparability_assessment_schema_scores_are_bounded() -> None:
    assessment = ComparabilityAssessmentCreate(
        canonical_field_id=1,
        source_product_id=1,
        target_product_id=2,
        scope_type=SpecificationScopeType.SKU,
        value_qualifier=ValueQualifier.EXACT,
        status=ComparabilityStatus.NEEDS_REVIEW,
        reason_code="scope_mismatch",
        explanation="Synthetic explanation.",
        overall_score=Decimal("0.2500"),
        review_status=ReviewStatus.PENDING_REVIEW,
    )
    assert assessment.status == ComparabilityStatus.NEEDS_REVIEW.value
    assert ComparabilityAssessmentList(total=1, items=[]).total == 1

    with pytest.raises(ValidationError):
        ComparabilityAssessmentCreate(
            canonical_field_id=1,
            source_product_id=1,
            target_product_id=2,
            scope_type=SpecificationScopeType.SKU,
            value_qualifier=ValueQualifier.EXACT,
            status=ComparabilityStatus.PARTIAL,
            reason_code="bad_score",
            explanation="Synthetic explanation.",
            overall_score=Decimal("1.5000"),
        )
