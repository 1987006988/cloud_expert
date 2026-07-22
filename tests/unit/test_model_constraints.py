from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    AliasType,
    AvailabilityStatus,
    CanonicalDomain,
    EvidenceType,
    MappingLevel,
    MappingStatus,
    ReviewStatus,
)
from cloud_expert.database.models.canonical import CanonicalFieldDefinition, NormalizedSpecification
from cloud_expert.database.models.mapping import ProductMapping
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import Product, ProductAlias
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Availability, Region
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.models.specification import ProductSpecification
from tests.fixtures.synthetic_data import load_synthetic_fixture


def test_provider_code_unique(session: Session) -> None:
    load_synthetic_fixture(session)
    session.add(
        Provider(
            code="synthetic_huawei",
            name="Duplicate Synthetic",
            display_name="Duplicate Synthetic",
            provider_type="fixture",
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_product_requires_provider_and_category(session: Session) -> None:
    session.add(
        Product(
            provider_id=999,
            category_id=999,
            market_mode="domestic",
            code="synthetic_orphan_product",
            official_name="Synthetic Orphan",
            display_name="Synthetic Orphan",
            product_status="unknown",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_product_alias_deduplicates_per_product(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    product_id = fixture["product"].id
    session.add(
        ProductAlias(
            product_id=product_id,
            alias="Synthetic Compute Alias",
            alias_type=AliasType.ENGLISH_NAME.value,
            language="en",
            is_official=False,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_region_code_unique_within_provider(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    region = fixture["region"]
    session.add(
        Region(
            provider_id=region.provider_id,
            code=region.code,
            name="Duplicate Synthetic Region",
            country_code="CN",
            market_mode="domestic",
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_evidence_requires_source_document_and_confidence_range(session: Session) -> None:
    session.add(
        Evidence(
            source_document_id=999,
            locator="html:#missing",
            excerpt="Synthetic orphan evidence.",
            evidence_type=EvidenceType.HTML_SECTION.value,
            confidence=0.5,
            review_status=ReviewStatus.PENDING_REVIEW.value,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()
    fixture = load_synthetic_fixture(session)
    session.add(
        Evidence(
            source_document_id=fixture["source_document"].id,
            locator="html:#bad-confidence",
            excerpt="Synthetic bad confidence.",
            evidence_type=EvidenceType.HTML_SECTION.value,
            confidence=1.5,
            review_status=ReviewStatus.PENDING_REVIEW.value,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_price_snapshot_rejects_negative_price_and_preserves_history(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    price_sku_id = fixture["price_sku"].id
    evidence_id = fixture["evidence"].id

    session.add(
        PriceSnapshot(
            price_sku_id=price_sku_id,
            unit_price=Decimal("-0.01"),
            discount_type="list",
            evidence_id=evidence_id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()

    session.rollback()
    session.add(
        PriceSnapshot(
            price_sku_id=price_sku_id,
            unit_price=Decimal("0.22340000"),
            discount_type="list",
            evidence_id=evidence_id,
        )
    )
    session.commit()

    snapshots = session.query(PriceSnapshot).filter_by(price_sku_id=price_sku_id).all()
    assert len(snapshots) == 2
    assert {snapshot.unit_price for snapshot in snapshots} == {
        Decimal("0.12340000"),
        Decimal("0.22340000"),
    }


def test_time_ranges_are_validated(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    session.add(
        PriceSnapshot(
            price_sku_id=fixture["price_sku"].id,
            unit_price=Decimal("0.10"),
            discount_type="list",
            effective_from=datetime(2026, 1, 2, tzinfo=UTC),
            effective_to=datetime(2026, 1, 1, tzinfo=UTC),
            evidence_id=fixture["evidence"].id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_mapping_status_and_not_self_mapping(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    session.add(
        ProductMapping(
            source_product_id=fixture["product"].id,
            target_product_id=fixture["product"].id,
            mapping_level=MappingLevel.PRODUCT.value,
            mapping_status=MappingStatus.PENDING_REVIEW.value,
            scenario_code="synthetic_self_mapping",
            review_status=ReviewStatus.PENDING_REVIEW.value,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_product_specification_requires_exactly_one_value(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    session.add(
        ProductSpecification(
            product_id=fixture["product"].id,
            definition_id=fixture["definition"].id,
            numeric_value=Decimal("1"),
            text_value="synthetic mixed value",
            raw_value="synthetic mixed",
            evidence_id=fixture["evidence"].id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_normalized_specification_requires_exactly_one_value(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    field = CanonicalFieldDefinition(
        code="synthetic.canonical.vcpu_count",
        name="Synthetic canonical vCPU",
        domain=CanonicalDomain.COMPUTE.value,
        data_type="numeric",
        canonical_unit="count",
        default_qualifier="exact",
        default_scope_type="sku",
        is_comparable=True,
        is_active=True,
    )
    session.add(field)
    session.flush()
    session.add(
        NormalizedSpecification(
            product_specification_id=fixture["specification"].id,
            product_id=fixture["product"].id,
            sku_id=fixture["sku"].id,
            canonical_field_id=field.id,
            normalization_rule_id=999999,
            evidence_id=fixture["evidence"].id,
            scope_type="sku",
            scope_identity="synthetic-sku-a",
            value_qualifier="exact",
            numeric_value=Decimal("2"),
            text_value="bad mixed",
            raw_value="2",
            canonical_value="2",
            canonical_unit="count",
            review_status=ReviewStatus.PENDING_REVIEW.value,
            source_value_hash="synthetic-hash",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_availability_positive_status_requires_evidence(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    session.add(
        Availability(
            product_id=fixture["product"].id,
            region_id=fixture["region"].id,
            availability_status=AvailabilityStatus.AVAILABLE.value,
            public_preview=False,
            generally_available=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
