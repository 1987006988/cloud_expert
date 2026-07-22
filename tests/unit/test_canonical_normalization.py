from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    AuthorityLevel,
    DataType,
    EvidenceType,
    MarketMode,
    ParserRunStatus,
    ProductStatus,
    ReviewStatus,
    SourceType,
)
from cloud_expert.database.models.canonical import ComparabilityAssessment, NormalizedSpecification
from cloud_expert.database.models.parsing import ParsedFieldCandidate, ParsingRun
from cloud_expert.database.models.product import SKU, Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition
from cloud_expert.normalization.canonical_fields import (
    LegacyFieldMapping,
    validate_canonical_registry,
)
from cloud_expert.normalization.canonical_service import (
    _infer_scope,
    assess_comparability,
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


def test_assess_comparability_creates_and_updates_blocker_aware_records(
    session: Session,
) -> None:
    category = ProductCategory(code="compute", name="Compute")
    huawei = Provider(
        code="huawei_cloud",
        name="Huawei Cloud",
        display_name="Huawei Cloud",
        provider_type="public_cloud",
    )
    aws = Provider(
        code="aws",
        name="AWS",
        display_name="AWS",
        provider_type="public_cloud",
    )
    session.add_all([category, huawei, aws])
    session.flush()
    ecs = _product(huawei.id, category.id, "ecs")
    ec2 = _product(aws.id, category.id, "ec2")
    session.add_all([ecs, ec2])
    session.flush()
    ecs_sku = SKU(
        product_id=ecs.id,
        provider_sku_code="ecs.synthetic.large",
        name="ECS Synthetic Large",
        status="unknown",
    )
    ec2_sku = SKU(
        product_id=ec2.id,
        provider_sku_code="ec2.synthetic.large",
        name="EC2 Synthetic Large",
        status="unknown",
    )
    session.add_all([ecs_sku, ec2_sku])
    session.flush()

    huawei_evidence = _evidence(session, huawei.id, "huawei")
    aws_evidence = _evidence(session, aws.id, "aws")
    definition = SpecificationDefinition(
        code="compute.vcpu_count",
        name="vCPU count",
        category_id=category.id,
        data_type=DataType.NUMERIC.value,
        canonical_unit="count",
        is_required=False,
    )
    session.add(definition)
    session.flush()
    session.add_all(
        [
            _spec(ecs.id, ecs_sku.id, definition.id, huawei_evidence.id, Decimal("4")),
            _spec(ec2.id, ec2_sku.id, definition.id, aws_evidence.id, Decimal("4")),
        ]
    )
    session.flush()

    normalize_specifications(session, run_key="comparability-flow-test")
    created = assess_comparability(session, run_key="comparability-flow-test")
    updated = assess_comparability(session, run_key="comparability-flow-test")

    assert created.assessments_created == 19
    assert updated.assessments_updated == 19
    assert created.status_counts["comparable"] == 1
    assert created.status_counts["not_comparable"] == 18
    assessments = session.scalars(select(ComparabilityAssessment)).all()
    assert len(assessments) == 19
    assert any(item.reason_code == "field_unit_scope_aligned" for item in assessments)


def test_infer_scope_uses_parser_candidate_target_identity(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    mapping = LegacyFieldMapping(
        source_field_code="object_storage.durability_percentage",
        canonical_field_code="object_storage.reliability.durability_percentage",
        value_qualifier="designed",
        scope_type="service_tier",
    )
    definition = SpecificationDefinition(
        code="object_storage.durability_percentage",
        name="Durability",
        category_id=fixture["category"].id,
        data_type=DataType.NUMERIC.value,
        canonical_unit="percent",
        is_required=False,
    )
    session.add(definition)
    session.flush()
    spec = ProductSpecification(
        product_id=fixture["product"].id,
        definition_id=definition.id,
        numeric_value=Decimal("99.999999999"),
        raw_value="99.999999999%",
        raw_unit="percent",
        canonical_value="99.999999999",
        canonical_unit="percent",
        evidence_id=fixture["evidence"].id,
    )
    run = ParsingRun(
        source_id="synthetic_parser_run",
        source_document_id=fixture["source_document"].id,
        parser_name="synthetic_parser",
        parser_version="v1",
        started_at=fixture["source_document"].captured_at,
        status=ParserRunStatus.SUCCEEDED.value,
    )
    session.add_all([spec, run])
    session.flush()
    session.add(
        ParsedFieldCandidate(
            parsing_run_id=run.id,
            source_document_id=fixture["source_document"].id,
            evidence_id=fixture["evidence"].id,
            target_table="service_tier",
            target_identity="synthetic-tier",
            field_code="object_storage.durability_percentage",
            raw_value="99.999999999%",
            normalized_value="99.999999999",
            canonical_unit="percent",
            locator="html:#synthetic",
            excerpt="Synthetic durability row.",
            confidence=0.9,
            review_status=ReviewStatus.MACHINE_EXTRACTED.value,
            parser_rule="synthetic_rule",
            value_hash="synthetic-value-hash",
        )
    )
    session.flush()

    scope_type, scope_identity = _infer_scope(
        session,
        spec,
        "object_storage.durability_percentage",
        mapping,
    )
    assert scope_type == "service_tier"
    assert scope_identity == "synthetic-tier"

    fallback_mapping = LegacyFieldMapping(
        source_field_code="object_storage.availability_percentage",
        canonical_field_code="object_storage.reliability.availability_percentage",
        value_qualifier="designed",
        scope_type="service_tier",
    )
    fallback_scope, fallback_identity = _infer_scope(
        session,
        spec,
        "object_storage.availability_percentage",
        fallback_mapping,
    )
    assert fallback_scope == "product"
    assert fallback_identity == f"product:{fixture['product'].id}"


def _product(provider_id: int, category_id: int, code: str) -> Product:
    return Product(
        provider_id=provider_id,
        category_id=category_id,
        market_mode=MarketMode.INTERNATIONAL.value,
        code=code,
        official_name=f"Synthetic {code}",
        display_name=f"Synthetic {code}",
        product_status=ProductStatus.UNKNOWN.value,
    )


def _evidence(session: Session, provider_id: int, label: str) -> Evidence:
    source = SourceDocument(
        provider_id=provider_id,
        source_type=SourceType.DOCUMENTATION.value,
        title=f"Synthetic {label} source",
        url=f"https://example.invalid/{label}/source",
        authority_level=AuthorityLevel.UNKNOWN.value,
        content_hash=f"synthetic-{label}-hash",
        http_status=200,
        is_current=True,
    )
    session.add(source)
    session.flush()
    evidence = Evidence(
        source_document_id=source.id,
        locator=f"html:#{label}",
        excerpt=f"Synthetic {label} excerpt.",
        evidence_type=EvidenceType.HTML_SECTION.value,
        confidence=0.95,
        review_status=ReviewStatus.MACHINE_EXTRACTED.value,
    )
    session.add(evidence)
    session.flush()
    return evidence


def _spec(
    product_id: int,
    sku_id: int,
    definition_id: int,
    evidence_id: int,
    value: Decimal,
) -> ProductSpecification:
    return ProductSpecification(
        product_id=product_id,
        sku_id=sku_id,
        definition_id=definition_id,
        numeric_value=value,
        raw_value=str(value),
        raw_unit="count",
        canonical_value=str(value),
        canonical_unit="count",
        evidence_id=evidence_id,
    )
