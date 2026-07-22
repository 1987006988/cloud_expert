from decimal import Decimal

from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    AliasType,
    AuthorityLevel,
    BillingMode,
    ChargeCategory,
    DataType,
    DiscountType,
    EvidenceType,
    MappingLevel,
    MappingStatus,
    MarketMode,
    ProductStatus,
    ReviewStatus,
    SourceType,
)
from cloud_expert.database.models.mapping import ProductMapping
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import SKU, Product, ProductAlias, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition


def load_synthetic_fixture(session: Session) -> dict[str, object]:
    """Create a minimal synthetic dataset for tests only."""

    synthetic_huawei = Provider(
        code="synthetic_huawei",
        name="Synthetic Huawei Provider",
        display_name="Synthetic Huawei",
        provider_type="fixture",
        official_website="https://example.invalid/synthetic-huawei",
        is_active=True,
    )
    synthetic_aws = Provider(
        code="synthetic_aws",
        name="Synthetic AWS Provider",
        display_name="Synthetic AWS",
        provider_type="fixture",
        official_website="https://example.invalid/synthetic-aws",
        is_active=True,
    )
    category = ProductCategory(
        code="compute",
        name="Synthetic Compute",
        description="Synthetic compute category for tests.",
    )
    session.add_all([synthetic_huawei, synthetic_aws, category])
    session.flush()

    product_a = Product(
        provider_id=synthetic_huawei.id,
        category_id=category.id,
        market_mode=MarketMode.DOMESTIC.value,
        code="synthetic_compute_a",
        official_name="Synthetic Compute A",
        display_name="Synthetic Compute A",
        product_status=ProductStatus.UNKNOWN.value,
        official_url="https://example.invalid/products/synthetic-compute-a",
    )
    product_b = Product(
        provider_id=synthetic_aws.id,
        category_id=category.id,
        market_mode=MarketMode.INTERNATIONAL.value,
        code="synthetic_compute_b",
        official_name="Synthetic Compute B",
        display_name="Synthetic Compute B",
        product_status=ProductStatus.UNKNOWN.value,
        official_url="https://example.invalid/products/synthetic-compute-b",
    )
    session.add_all([product_a, product_b])
    session.flush()

    alias = ProductAlias(
        product_id=product_a.id,
        alias="Synthetic Compute Alias",
        alias_type=AliasType.ENGLISH_NAME.value,
        language="en",
        is_official=False,
    )
    sku = SKU(
        product_id=product_a.id,
        provider_sku_code="synthetic-sku-a",
        name="Synthetic SKU A",
        status="unknown",
    )
    region = Region(
        provider_id=synthetic_huawei.id,
        code="synthetic-cn-1",
        name="Synthetic CN Region 1",
        country_code="CN",
        geography="synthetic-geography",
        market_mode=MarketMode.DOMESTIC.value,
        is_active=True,
    )
    session.add_all([alias, sku, region])
    session.flush()

    source_document = SourceDocument(
        provider_id=synthetic_huawei.id,
        source_type=SourceType.DOCUMENTATION.value,
        title="Synthetic fixture source",
        url="https://example.invalid/sources/synthetic-fixture",
        language="en",
        authority_level=AuthorityLevel.UNKNOWN.value,
        content_hash="synthetic-content-hash-001",
        mime_type="text/html",
        http_status=200,
        is_current=True,
    )
    session.add(source_document)
    session.flush()

    evidence = Evidence(
        source_document_id=source_document.id,
        section_title="Synthetic section",
        locator="html:#synthetic",
        excerpt="Synthetic excerpt for fixture validation only.",
        evidence_type=EvidenceType.HTML_SECTION.value,
        confidence=0.75,
        review_status=ReviewStatus.PENDING_REVIEW.value,
    )
    session.add(evidence)
    session.flush()

    definition = SpecificationDefinition(
        code="synthetic_vcpu_count",
        name="Synthetic vCPU Count",
        category_id=category.id,
        data_type=DataType.NUMERIC.value,
        canonical_unit="count",
        is_required=False,
    )
    session.add(definition)
    session.flush()

    specification = ProductSpecification(
        product_id=product_a.id,
        sku_id=sku.id,
        definition_id=definition.id,
        numeric_value=Decimal("2"),
        raw_value="synthetic 2",
        raw_unit="count",
        canonical_value="2",
        canonical_unit="count",
        evidence_id=evidence.id,
    )
    price_sku = PriceSKU(
        provider_id=synthetic_huawei.id,
        product_id=product_a.id,
        sku_id=sku.id,
        region_id=region.id,
        provider_price_code="synthetic-price-a",
        charge_category=ChargeCategory.COMPUTE.value,
        billing_mode=BillingMode.ON_DEMAND.value,
        billing_unit="synthetic-hour",
        currency="USD",
        tax_included=False,
    )
    mapping = ProductMapping(
        source_product_id=product_a.id,
        target_product_id=product_b.id,
        mapping_level=MappingLevel.PRODUCT.value,
        mapping_status=MappingStatus.PENDING_REVIEW.value,
        scenario_code="synthetic_scenario",
        rationale="Synthetic mapping for repository tests.",
        evidence_id=evidence.id,
        review_status=ReviewStatus.PENDING_REVIEW.value,
    )
    session.add_all([specification, price_sku, mapping])
    session.flush()

    snapshot = PriceSnapshot(
        price_sku_id=price_sku.id,
        unit_price=Decimal("0.12340000"),
        minimum_quantity=Decimal("0"),
        billing_period="synthetic-hour",
        discount_type=DiscountType.LIST.value,
        evidence_id=evidence.id,
        source_payload_path="tests/fixtures/synthetic_price_payload.json",
    )
    session.add(snapshot)
    session.commit()

    return {
        "provider": synthetic_huawei,
        "competitor_provider": synthetic_aws,
        "category": category,
        "product": product_a,
        "competitor_product": product_b,
        "alias": alias,
        "sku": sku,
        "region": region,
        "source_document": source_document,
        "evidence": evidence,
        "definition": definition,
        "specification": specification,
        "price_sku": price_sku,
        "snapshot": snapshot,
        "mapping": mapping,
    }
