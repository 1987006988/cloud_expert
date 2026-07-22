from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from cloud_expert.config.settings import PROJECT_ROOT, get_settings
from cloud_expert.database.enums import (
    AvailabilityStatus,
    ClaimType,
    MappingLevel,
    MappingStatus,
    MarketMode,
    ReviewStatus,
)
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.session import get_session, make_engine
from cloud_expert.schemas.competition import CompetitiveClaimCreate, CompetitiveClaimUpdate
from cloud_expert.schemas.mapping import ProductMappingCreate
from cloud_expert.schemas.pricing import PriceSKUUpdate, PriceSnapshotUpdate
from cloud_expert.schemas.region import AvailabilityCreate, RegionCreate, RegionUpdate


def test_settings_read_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./synthetic_settings.sqlite")
    expected = f"sqlite:///{(PROJECT_ROOT / 'synthetic_settings.sqlite').as_posix()}"
    assert get_settings().database_url == expected
    get_settings.cache_clear()


def test_make_engine_and_get_session() -> None:
    engine = make_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
    engine.dispose()

    generator = get_session()
    session = next(generator)
    assert session is not None
    with pytest.raises(StopIteration):
        generator.close()
        next(generator)


def test_repr_includes_id_and_code() -> None:
    provider = Provider(
        id=123,
        code="synthetic_repr",
        name="Synthetic Repr",
        display_name="Synthetic Repr",
        provider_type="fixture",
        is_active=True,
    )
    rendered = repr(provider)
    assert "id=123" in rendered
    assert "synthetic_repr" in rendered


def test_region_schema_country_code_validation() -> None:
    region = RegionCreate(
        provider_id=1,
        code="synthetic-cn-1",
        name="Synthetic CN 1",
        country_code="cn",
        market_mode=MarketMode.DOMESTIC,
    )
    assert region.country_code == "CN"

    with pytest.raises(ValidationError):
        RegionUpdate(country_code="CHN")


def test_availability_schema_requires_evidence_for_positive_status() -> None:
    AvailabilityCreate(
        product_id=1,
        region_id=1,
        availability_status=AvailabilityStatus.UNKNOWN,
    )

    with pytest.raises(ValidationError):
        AvailabilityCreate(
            product_id=1,
            region_id=1,
            availability_status=AvailabilityStatus.AVAILABLE,
            generally_available=True,
        )


def test_mapping_schema_accepts_directional_pending_review_mapping() -> None:
    mapping = ProductMappingCreate(
        source_product_id=1,
        target_product_id=2,
        mapping_level=MappingLevel.PRODUCT,
        mapping_status=MappingStatus.PENDING_REVIEW,
        scenario_code="synthetic_mapping_scenario",
        review_status=ReviewStatus.PENDING_REVIEW,
    )
    assert mapping.source_product_id == 1
    assert mapping.target_product_id == 2


def test_competitive_claim_schema_validates_confidence_and_time_range() -> None:
    claim = CompetitiveClaimCreate(
        market_mode=MarketMode.DOMESTIC,
        source_product_id=1,
        target_product_id=2,
        scenario_code="synthetic_claim_scenario",
        claim_type=ClaimType.NEUTRAL_DIFFERENCE,
        claim_text="Synthetic claim text for validation only.",
        applicable_conditions="Synthetic conditions.",
        limitations="Synthetic limitations.",
        evidence_id=1,
        confidence=0.5,
        review_status=ReviewStatus.PENDING_REVIEW,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        valid_to=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert claim.confidence == 0.5

    with pytest.raises(ValidationError):
        CompetitiveClaimUpdate(
            confidence=0.2,
            valid_from=datetime(2026, 1, 2, tzinfo=UTC),
            valid_to=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_pricing_update_schemas_validate_optional_fields() -> None:
    assert PriceSKUUpdate(currency="usd").currency == "USD"

    with pytest.raises(ValidationError):
        PriceSKUUpdate(currency="US")

    with pytest.raises(ValidationError):
        PriceSnapshotUpdate(
            minimum_quantity=2,
            maximum_quantity=1,
        )
