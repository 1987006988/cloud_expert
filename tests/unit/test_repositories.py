from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud_expert.common.exceptions import NotFoundError
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.repositories import (
    CanonicalFieldDefinitionRepository,
    EvidenceRepository,
    PriceSnapshotRepository,
    ProductMappingRepository,
    ProductRepository,
    ProviderRepository,
    RegionRepository,
    SourceDocumentRepository,
)
from tests.fixtures.synthetic_data import load_synthetic_fixture


def test_provider_repository_create_read_update_list_deactivate(session: Session) -> None:
    repo = ProviderRepository(session)
    created = repo.create(
        {
            "code": "synthetic_repo_provider",
            "name": "Synthetic Repo Provider",
            "display_name": "Synthetic Repo",
            "provider_type": "fixture",
            "is_active": True,
        }
    )
    assert repo.get_by_id(created.id) is not None
    assert repo.get_by_code("synthetic_repo_provider") == created

    updated = repo.update(created.id, {"display_name": "Synthetic Repo Updated"})
    assert updated is not None
    assert updated.display_name == "Synthetic Repo Updated"

    assert repo.list({"is_active": True})
    inactive = repo.deactivate(created.id)
    assert inactive.is_active is False
    assert repo.get_by_id(999999) is None
    with pytest.raises(NotFoundError):
        repo.require_by_id(999999)


def test_repositories_filter_core_entities(session: Session) -> None:
    fixture = load_synthetic_fixture(session)

    assert ProductRepository(session).list_by_provider(fixture["provider"].id)
    assert RegionRepository(session).list_by_provider(fixture["provider"].id)
    assert SourceDocumentRepository(session).get_by_url_hash(
        "https://example.invalid/sources/synthetic-fixture",
        "synthetic-content-hash-001",
    )
    assert EvidenceRepository(session).list({"source_document_id": fixture["source_document"].id})
    assert ProductMappingRepository(session).list_for_source_product(fixture["product"].id)
    assert PriceSnapshotRepository(session).list_for_price_sku(fixture["price_sku"].id)


def test_canonical_field_repository_get_by_code(session: Session) -> None:
    from cloud_expert.normalization.canonical_service import seed_canonical_registry

    seed_canonical_registry(session)
    repo = CanonicalFieldDefinitionRepository(session)
    field = repo.get_by_code("compute.cpu.vcpu_count")
    assert field is not None
    assert field.canonical_unit == "count"
    assert repo.list_active()


def test_repository_transaction_rolls_back(session: Session) -> None:
    repo = ProviderRepository(session)
    with pytest.raises(RuntimeError), repo.transaction():
        repo.create(
            {
                "code": "synthetic_rollback_provider",
                "name": "Synthetic Rollback",
                "display_name": "Synthetic Rollback",
                "provider_type": "fixture",
                "is_active": True,
            }
        )
        raise RuntimeError("synthetic rollback")

    assert repo.get_by_code("synthetic_rollback_provider") is None


def test_repository_unique_and_foreign_key_conflicts(session: Session) -> None:
    fixture = load_synthetic_fixture(session)
    repo = ProviderRepository(session)
    with pytest.raises(IntegrityError):
        repo.create(
            {
                "code": fixture["provider"].code,
                "name": "Duplicate Synthetic",
                "display_name": "Duplicate Synthetic",
                "provider_type": "fixture",
                "is_active": True,
            }
        )

    session.rollback()
    session.add(
        PriceSnapshot(
            price_sku_id=999999,
            unit_price=Decimal("0.10"),
            discount_type="list",
            evidence_id=fixture["evidence"].id,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
