from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from cloud_expert.database.enums import (
    AuthorityLevel,
    BillingMode,
    ChargeCategory,
    DataType,
    DiscountType,
    EvidenceType,
    MarketMode,
    ProductStatus,
    ReviewStatus,
    SourceType,
)
from cloud_expert.database.models.provider import Provider
from cloud_expert.schemas.pricing import PriceSKUCreate, PriceSnapshotCreate
from cloud_expert.schemas.product import ProductCreate, ProductUpdate
from cloud_expert.schemas.provider import ProviderCreate, ProviderRead, ProviderUpdate
from cloud_expert.schemas.source import EvidenceCreate, SourceDocumentCreate
from cloud_expert.schemas.specification import (
    ProductSpecificationCreate,
    SpecificationDefinitionCreate,
)


def test_valid_provider_input_and_read_from_orm() -> None:
    create = ProviderCreate(
        code="synthetic_schema_provider",
        name="Synthetic Schema Provider",
        display_name="Synthetic Schema",
        provider_type="fixture",
        official_website="https://example.invalid/schema-provider",
    )
    assert create.code == "synthetic_schema_provider"

    orm_provider = Provider(
        id=1,
        code=create.code,
        name=create.name,
        display_name=create.display_name,
        provider_type=create.provider_type,
        official_website=create.official_website,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    read = ProviderRead.model_validate(orm_provider)
    assert read.id == 1


def test_invalid_url_fails() -> None:
    with pytest.raises(ValidationError):
        ProviderCreate(
            code="synthetic_bad_url",
            name="Synthetic Bad URL",
            display_name="Synthetic Bad URL",
            provider_type="fixture",
            official_website="not-a-url",
        )


def test_invalid_confidence_fails() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(
            source_document_id=1,
            locator="html:#synthetic",
            excerpt="Synthetic excerpt.",
            evidence_type=EvidenceType.HTML_SECTION,
            confidence=1.1,
            review_status=ReviewStatus.PENDING_REVIEW,
        )


def test_invalid_currency_fails() -> None:
    with pytest.raises(ValidationError):
        PriceSKUCreate(
            provider_id=1,
            product_id=1,
            region_id=1,
            provider_price_code="synthetic-price",
            charge_category=ChargeCategory.COMPUTE,
            billing_mode=BillingMode.ON_DEMAND,
            billing_unit="synthetic-hour",
            currency="US",
        )


def test_update_model_allows_partial_fields() -> None:
    update = ProductUpdate(display_name="Synthetic Partial Update")
    assert update.display_name == "Synthetic Partial Update"
    provider_update = ProviderUpdate(is_active=False)
    assert provider_update.is_active is False


def test_core_create_schemas_validate() -> None:
    product = ProductCreate(
        provider_id=1,
        category_id=1,
        market_mode=MarketMode.DOMESTIC,
        code="synthetic_product",
        official_name="Synthetic Product",
        display_name="Synthetic Product",
        product_status=ProductStatus.UNKNOWN,
        official_url="https://example.invalid/products/synthetic",
    )
    assert product.market_mode == MarketMode.DOMESTIC.value

    SourceDocumentCreate(
        provider_id=1,
        source_type=SourceType.DOCUMENTATION,
        title="Synthetic Source",
        url="https://example.invalid/source",
        authority_level=AuthorityLevel.UNKNOWN,
        content_hash="synthetic-hash",
    )
    SpecificationDefinitionCreate(
        code="synthetic_spec",
        name="Synthetic Spec",
        category_id=1,
        data_type=DataType.NUMERIC,
        canonical_unit="count",
    )
    ProductSpecificationCreate(
        product_id=1,
        definition_id=1,
        numeric_value=Decimal("1"),
        raw_value="synthetic raw",
        evidence_id=1,
    )
    PriceSnapshotCreate(
        price_sku_id=1,
        unit_price=Decimal("0.10"),
        minimum_quantity=Decimal("0"),
        maximum_quantity=Decimal("1"),
        discount_type=DiscountType.LIST,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 1, 2, tzinfo=UTC),
        evidence_id=1,
    )


def test_product_specification_rejects_mixed_value_fields() -> None:
    with pytest.raises(ValidationError):
        ProductSpecificationCreate(
            product_id=1,
            definition_id=1,
            numeric_value=Decimal("1"),
            text_value="synthetic",
            raw_value="synthetic raw",
            evidence_id=1,
        )
