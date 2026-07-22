import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud_expert.database.enums import (
    AuthorityLevel,
    CanonicalDomain,
    ChangeStatus,
    ChargeCategory,
    DataType,
    DiscountType,
    EvidenceType,
    MarketMode,
    NormalizationRuleType,
    NormalizationRunStatus,
    ProductStatus,
    ReviewStatus,
    SourceType,
    SpecificationScopeType,
    ValueQualifier,
)
from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    NormalizationRule,
    NormalizationRun,
    NormalizedSpecification,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification, SpecificationDefinition

pytestmark = pytest.mark.postgres


@pytest.fixture()
def postgres_database_url() -> str:
    url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    if not url.startswith("postgresql"):
        pytest.fail("POSTGRES_TEST_DATABASE_URL must point to PostgreSQL")
    if "_r011_" not in url:
        pytest.fail("POSTGRES_TEST_DATABASE_URL must point to an isolated R011 test database")
    return url


@pytest.fixture()
def postgres_engine(postgres_database_url: str) -> Iterator[Engine]:
    engine = create_engine(postgres_database_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def postgres_session(postgres_engine: Engine) -> Iterator[Session]:
    with Session(postgres_engine, future=True) as session:
        yield session
        session.rollback()


def test_schema_has_expected_postgresql_types_and_constraints(postgres_engine: Engine) -> None:
    inspector = inspect(postgres_engine)

    assert inspector.get_check_constraints("product")
    assert inspector.get_check_constraints("normalized_specification")
    assert inspector.get_unique_constraints("provider")
    assert inspector.get_unique_constraints("normalized_specification")
    assert inspector.get_foreign_keys("evidence")
    assert inspector.get_foreign_keys("normalized_specification")
    assert inspector.get_indexes("snapshot_record")

    product_columns = {
        column["name"]: str(column["type"]).lower() for column in inspector.get_columns("product")
    }
    canonical_columns = {
        column["name"]: str(column["type"]).lower()
        for column in inspector.get_columns("canonical_field_definition")
    }
    price_columns = {
        column["name"]: str(column["type"]).lower()
        for column in inspector.get_columns("price_snapshot")
    }

    assert product_columns["metadata_json"] == "json"
    assert canonical_columns["metadata_json"] == "json"
    assert price_columns["unit_price"] == "numeric(24, 8)"

    with postgres_engine.connect() as connection:
        native_enum_count = connection.execute(
            text(
                """
                select count(*)
                from pg_type typ
                join pg_enum enum on typ.oid = enum.enumtypid
                """
            )
        ).scalar_one()
    assert native_enum_count == 0


def test_check_constraint_enforces_enum_like_values(postgres_session: Session) -> None:
    category = ProductCategory(code=_code("category"), name="R011 Category")
    provider = Provider(
        code=_code("provider"),
        name="R011 Provider",
        display_name="R011 Provider",
        provider_type="fixture",
        is_active=True,
    )
    postgres_session.add_all([category, provider])
    postgres_session.flush()

    valid = Product(
        provider_id=provider.id,
        category_id=category.id,
        market_mode=MarketMode.DOMESTIC.value,
        code=_code("product-valid"),
        official_name="R011 Product Valid",
        display_name="R011 Product Valid",
        product_status=ProductStatus.UNKNOWN.value,
        metadata_json={"nested": {"value": 1}, "empty": {}},
    )
    postgres_session.add(valid)
    postgres_session.flush()

    invalid = Product(
        provider_id=provider.id,
        category_id=category.id,
        market_mode="invalid_market",
        code=_code("product-invalid"),
        official_name="R011 Product Invalid",
        display_name="R011 Product Invalid",
        product_status=ProductStatus.UNKNOWN.value,
    )
    postgres_session.add(invalid)
    with pytest.raises(IntegrityError):
        postgres_session.flush()


def test_numeric_decimal_json_and_timezone_behavior(postgres_session: Session) -> None:
    fixture = _create_graph(postgres_session)
    price = PriceSnapshot(
        price_sku_id=fixture.price_sku_id,
        unit_price=Decimal("0.123456789"),
        minimum_quantity=Decimal("0"),
        maximum_quantity=Decimal("9.999999999"),
        discount_type=DiscountType.LIST.value,
        evidence_id=fixture.evidence_id,
    )
    postgres_session.add(price)
    postgres_session.flush()
    postgres_session.refresh(price)

    assert isinstance(price.unit_price, Decimal)
    assert price.unit_price == Decimal("0.12345679")
    assert price.maximum_quantity == Decimal("10.00000000")

    source_document = postgres_session.get(SourceDocument, fixture.source_document_id)
    assert source_document is not None
    assert source_document.published_at is not None
    assert source_document.published_at.tzinfo is not None

    timezone_name = postgres_session.execute(
        text("select current_setting('TimeZone')")
    ).scalar_one()
    assert timezone_name == "Etc/UTC"

    product = postgres_session.get(Product, fixture.product_id)
    assert product is not None
    assert product.metadata_json == {"r011": {"nested": True}, "empty": {}, "null_value": None}


def test_foreign_key_and_unique_constraints(postgres_session: Session) -> None:
    fixture = _create_graph(postgres_session)

    duplicate_provider = Provider(
        code=fixture.provider_code,
        name="Duplicate provider",
        display_name="Duplicate provider",
        provider_type="fixture",
        is_active=True,
    )
    postgres_session.add(duplicate_provider)
    with pytest.raises(IntegrityError):
        postgres_session.flush()
    postgres_session.rollback()

    fixture = _create_graph(postgres_session)
    duplicate_snapshot = SnapshotRecord(
        source_document_id=fixture.source_document_id,
        source_id=fixture.snapshot_source_id,
        content_hash=fixture.snapshot_hash,
        storage_path="r011/duplicate.html",
        manifest_path="r011/duplicate.json",
        content_type="text/html",
        content_length_bytes=1,
        captured_at=datetime.now(UTC),
        change_status=ChangeStatus.FIRST_SEEN.value,
        is_current=True,
    )
    postgres_session.add(duplicate_snapshot)
    with pytest.raises(IntegrityError):
        postgres_session.flush()
    postgres_session.rollback()

    invalid_evidence = Evidence(
        source_document_id=999_999_999,
        locator="html:#missing",
        excerpt="Invalid FK synthetic evidence.",
        evidence_type=EvidenceType.HTML_SECTION.value,
        confidence=Decimal("0.5"),
        review_status=ReviewStatus.PENDING_REVIEW.value,
    )
    postgres_session.add(invalid_evidence)
    with pytest.raises(IntegrityError):
        postgres_session.flush()
    postgres_session.rollback()

    fixture = _create_graph(postgres_session)
    product = postgres_session.get(Product, fixture.product_id)
    assert product is not None
    postgres_session.delete(product)
    with pytest.raises(IntegrityError):
        postgres_session.flush()


def test_transaction_rollback_leaves_no_partial_snapshot_chain(postgres_engine: Engine) -> None:
    marker = _code("rollback")
    with (
        pytest.raises(RuntimeError),
        Session(postgres_engine, future=True) as session,
        session.begin(),
    ):
        provider = Provider(
            code=marker,
            name="Rollback Provider",
            display_name="Rollback Provider",
            provider_type="fixture",
            is_active=True,
        )
        session.add(provider)
        session.flush()
        source_document = SourceDocument(
            provider_id=provider.id,
            source_type=SourceType.DOCUMENTATION.value,
            title="Rollback source",
            url=f"https://example.invalid/{marker}",
            authority_level=AuthorityLevel.UNKNOWN.value,
            content_hash=marker,
            is_current=True,
        )
        session.add(source_document)
        session.flush()
        session.add(
            SnapshotRecord(
                source_document_id=source_document.id,
                source_id=marker,
                content_hash=marker,
                storage_path="r011/rollback.html",
                manifest_path="r011/rollback.json",
                content_type="text/html",
                content_length_bytes=1,
                captured_at=datetime.now(UTC),
                change_status=ChangeStatus.FIRST_SEEN.value,
                is_current=True,
            )
        )
        raise RuntimeError("force rollback")

    with Session(postgres_engine, future=True) as session:
        assert session.query(Provider).filter_by(code=marker).count() == 0
        assert session.query(SourceDocument).filter_by(content_hash=marker).count() == 0
        assert session.query(SnapshotRecord).filter_by(source_id=marker).count() == 0


def test_concurrent_provider_creation_respects_unique_idempotency_boundary(
    postgres_database_url: str,
) -> None:
    provider_code = _code("concurrent-provider")

    def create_provider() -> str:
        engine = create_engine(postgres_database_url, future=True)
        try:
            with Session(engine, future=True) as session:
                session.add(
                    Provider(
                        code=provider_code,
                        name="Concurrent Provider",
                        display_name="Concurrent Provider",
                        provider_type="fixture",
                        is_active=True,
                    )
                )
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    return "duplicate"
                return "created"
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _: create_provider(), range(2)))

    assert results == ["created", "duplicate"]

    cleanup_engine = create_engine(postgres_database_url, future=True)
    try:
        with cleanup_engine.begin() as connection:
            connection.execute(
                text("delete from provider where code = :code"), {"code": provider_code}
            )
    finally:
        cleanup_engine.dispose()


class GraphFixture:
    def __init__(
        self,
        *,
        provider_code: str,
        product_id: int,
        source_document_id: int,
        evidence_id: int,
        price_sku_id: int,
        snapshot_source_id: str,
        snapshot_hash: str,
    ) -> None:
        self.provider_code = provider_code
        self.product_id = product_id
        self.source_document_id = source_document_id
        self.evidence_id = evidence_id
        self.price_sku_id = price_sku_id
        self.snapshot_source_id = snapshot_source_id
        self.snapshot_hash = snapshot_hash


def _create_graph(session: Session) -> GraphFixture:
    suffix = uuid4().hex
    provider = Provider(
        code=f"r011_provider_{suffix}",
        name="R011 Provider",
        display_name="R011 Provider",
        provider_type="fixture",
        is_active=True,
    )
    category = ProductCategory(code=f"r011_category_{suffix}", name="R011 Category")
    session.add_all([provider, category])
    session.flush()

    product = Product(
        provider_id=provider.id,
        category_id=category.id,
        market_mode=MarketMode.DOMESTIC.value,
        code=f"r011_product_{suffix}",
        official_name="R011 Product",
        display_name="R011 Product",
        product_status=ProductStatus.UNKNOWN.value,
        metadata_json={"r011": {"nested": True}, "empty": {}, "null_value": None},
    )
    region = Region(
        provider_id=provider.id,
        code=f"r011-region-{suffix}",
        name="R011 Region",
        country_code="CN",
        market_mode=MarketMode.DOMESTIC.value,
        is_active=True,
    )
    source_document = SourceDocument(
        provider_id=provider.id,
        source_type=SourceType.DOCUMENTATION.value,
        title="R011 Source",
        url=f"https://example.invalid/r011/{suffix}",
        authority_level=AuthorityLevel.UNKNOWN.value,
        published_at=datetime.now(UTC),
        content_hash=f"hash_{suffix}",
        is_current=True,
    )
    session.add_all([product, region, source_document])
    session.flush()

    snapshot = SnapshotRecord(
        source_document_id=source_document.id,
        source_id=f"r011_source_{suffix}",
        content_hash=f"snapshot_hash_{suffix}",
        storage_path="r011/synthetic.html",
        manifest_path="r011/synthetic.json",
        content_type="text/html",
        content_length_bytes=1,
        captured_at=datetime.now(UTC),
        change_status=ChangeStatus.FIRST_SEEN.value,
        is_current=True,
    )
    evidence = Evidence(
        source_document_id=source_document.id,
        snapshot_record_id=snapshot.id,
        locator="html:#r011",
        excerpt="R011 synthetic official evidence.",
        evidence_type=EvidenceType.HTML_SECTION.value,
        confidence=0.75,
        review_status=ReviewStatus.PENDING_REVIEW.value,
    )
    definition = SpecificationDefinition(
        code=f"r011_spec_{suffix}",
        name="R011 Specification",
        category_id=category.id,
        data_type=DataType.NUMERIC.value,
        canonical_unit="count",
        is_required=False,
    )
    session.add_all([snapshot, evidence, definition])
    session.flush()

    specification = ProductSpecification(
        product_id=product.id,
        definition_id=definition.id,
        numeric_value=Decimal("2"),
        raw_value="2",
        raw_unit="count",
        evidence_id=evidence.id,
    )
    price_sku = PriceSKU(
        provider_id=provider.id,
        product_id=product.id,
        region_id=region.id,
        provider_price_code=f"r011_price_{suffix}",
        charge_category=ChargeCategory.COMPUTE.value,
        billing_mode="on_demand",
        billing_unit="hour",
        currency="USD",
        tax_included=False,
    )
    canonical_field = CanonicalFieldDefinition(
        code=f"r011_canonical_{suffix}",
        name="R011 Canonical Field",
        domain=CanonicalDomain.COMPUTE.value,
        data_type=DataType.NUMERIC.value,
        canonical_unit="count",
        default_qualifier=ValueQualifier.EXACT.value,
        default_scope_type=SpecificationScopeType.PRODUCT.value,
        is_comparable=True,
        is_active=True,
    )
    run = NormalizationRun(
        run_key=f"r011_run_{suffix}",
        status=NormalizationRunStatus.SUCCEEDED.value,
        started_at=datetime.now(UTC),
        records_examined=1,
        records_created=1,
        records_updated=0,
        records_skipped=0,
        review_items_created=0,
    )
    session.add_all([specification, price_sku, canonical_field, run])
    session.flush()

    rule = NormalizationRule(
        code=f"r011_rule_{suffix}",
        version="v1",
        rule_type=NormalizationRuleType.FIELD_MAPPING.value,
        canonical_field_id=canonical_field.id,
        value_qualifier=ValueQualifier.EXACT.value,
        scope_type=SpecificationScopeType.PRODUCT.value,
        is_active=True,
    )
    session.add(rule)
    session.flush()
    session.add(
        NormalizedSpecification(
            product_specification_id=specification.id,
            product_id=product.id,
            canonical_field_id=canonical_field.id,
            normalization_rule_id=rule.id,
            normalization_run_id=run.id,
            evidence_id=evidence.id,
            scope_type=SpecificationScopeType.PRODUCT.value,
            scope_identity=product.code,
            value_qualifier=ValueQualifier.EXACT.value,
            numeric_value=Decimal("2"),
            raw_value="2",
            raw_unit="count",
            canonical_value="2",
            canonical_unit="count",
            quality_score=Decimal("1.0000"),
            review_status=ReviewStatus.PENDING_REVIEW.value,
            source_value_hash=f"value_hash_{suffix}",
        )
    )
    session.flush()

    return GraphFixture(
        provider_code=provider.code,
        product_id=product.id,
        source_document_id=source_document.id,
        evidence_id=evidence.id,
        price_sku_id=price_sku.id,
        snapshot_source_id=snapshot.source_id,
        snapshot_hash=snapshot.content_hash,
    )


def _code(prefix: str) -> str:
    return f"r011_{prefix}_{uuid4().hex}"
