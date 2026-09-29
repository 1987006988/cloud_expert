import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.pricing import extraction
from tests.fixtures.synthetic_data import load_synthetic_fixture


@pytest.fixture
def price_input(session, tmp_path, monkeypatch):
    fixture = load_synthetic_fixture(session)
    product = fixture["product"]
    provider = product.provider
    provider.code = "aws"
    product.code = "s3"
    product.market_mode = "international"
    fixture["region"].code = "us-east-1"
    fixture["region"].market_mode = "international"
    document = fixture["source_document"]
    document.source_type = "pricing"
    dimension = {
        "unit": "GB-Mo",
        "pricePerUnit": {"USD": "1.25"},
        "description": "Synthetic storage price; not a real cloud price",
        "beginRange": "0",
        "endRange": "500",
    }
    payload = {
        "products": {
            "SYNTHETIC": {
                "productFamily": "Storage",
                "attributes": {
                    "location": "US East (N. Virginia)",
                    "storageClass": "Standard",
                    "volumeType": "Standard",
                    "usagetype": "TimedStorage-ByteHrs",
                },
            }
        },
        "terms": {"OnDemand": {"SYNTHETIC": {"offer": {"priceDimensions": {"rate": dimension}}}}},
    }
    raw = json.dumps(payload).encode()
    document.content_hash = sha256(raw).hexdigest()
    document.is_current = True
    (tmp_path / "price.json").write_bytes(raw)
    snapshot = SnapshotRecord(
        source_document_id=document.id,
        source_id=extraction.AWS_S3_STANDARD_SOURCE_ID,
        content_hash=document.content_hash,
        storage_path="price.json",
        manifest_path="manifest.json",
        content_type="application/json",
        content_length_bytes=len(raw),
        captured_at=datetime.now(UTC),
        change_status="first_seen",
        is_current=True,
    )
    session.add(snapshot)
    session.flush()
    monkeypatch.setattr(extraction, "_raw_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        extraction,
        "load_registry_entries",
        lambda: [SimpleNamespace(source_id=snapshot.source_id, terms_review_status="approved")],
    )
    return snapshot, document, dimension


def test_price_snapshot_extraction_persistence_and_idempotency(session, price_input):
    snapshot, document, _ = price_input
    snapshot.captured_at = datetime.now(UTC) - timedelta(days=30)
    records = extraction.extract_price_records(session)
    assert len(records) == 1
    record = records[0]
    assert record.unit_price == Decimal("1.25")
    assert record.maximum_quantity == Decimal("500")
    assert record.snapshot_record_id == snapshot.id
    assert record.source_document_id == document.id
    result = extraction.persist_price_records(session, records)
    assert result["created_price_skus"] == 1
    assert result["created_price_snapshots"] == 1
    assert not result["skipped_records"]
    again = extraction.persist_price_records(session, extraction.extract_price_records(session))
    assert again["created_price_skus"] == again["created_price_snapshots"] == 0
    stored = session.scalar(
        select(PriceSnapshot).where(PriceSnapshot.source_payload_path == record.source_payload_path)
    )
    assert stored.evidence.snapshot_record_id == snapshot.id
    assert extraction._utc(stored.captured_at) == extraction._utc(snapshot.captured_at)
    from cloud_expert.pricing.freshness import price_snapshot_freshness

    assert price_snapshot_freshness(stored) == "stale"
    for override in (
        {"provider_code": "missing"},
        {"product_code": "missing"},
        {"region_code": "missing"},
    ):
        skipped = extraction.persist_price_records(session, [replace(record, **override)])
        assert len(skipped["skipped_records"]) == 1
        assert skipped["created_price_snapshots"] == 0


def test_persistence_rechecks_snapshot_and_price_scope(session, price_input):
    records = extraction.extract_price_records(session)
    record = records[0]
    result = extraction.persist_price_records(session, [replace(record, snapshot_record_id=-1)])
    assert result["created_price_snapshots"] == 0
    assert "source snapshot" in result["skipped_records"][0]["reason"]
    extraction.persist_price_records(session, records)
    result = extraction.persist_price_records(session, [replace(record, currency="CNY")])
    assert result["created_price_snapshots"] == 0
    assert "scope conflict" in result["skipped_records"][0]["reason"]


def test_legacy_capture_time_conflict_is_reported_not_overwritten(session, price_input):
    record = extraction.extract_price_records(session)[0]
    extraction.persist_price_records(session, [record])
    stored = session.scalar(
        select(PriceSnapshot).where(PriceSnapshot.source_payload_path == record.source_payload_path)
    )
    old_value = stored.captured_at + timedelta(days=1)
    stored.captured_at = old_value
    session.commit()
    result = extraction.persist_price_records(session, [record])
    assert result["created_price_snapshots"] == 0
    assert "controlled correction" in result["skipped_records"][0]["reason"]
    assert stored.captured_at == old_value


def test_existing_price_scope_and_evidence_are_not_silently_replaced(session, price_input):
    record = extraction.extract_price_records(session)[0]
    extraction.persist_price_records(session, [record])
    stored = session.scalar(
        select(PriceSnapshot).where(PriceSnapshot.source_payload_path == record.source_payload_path)
    )
    stored.maximum_quantity = Decimal("1000")
    session.commit()
    result = extraction.persist_price_records(session, [record])
    assert result["skipped_records"] == [{"reason": "existing PriceSnapshot scope conflict"}]
    assert stored.maximum_quantity == Decimal("1000")
    stored.evidence.excerpt = "tampered"
    session.flush()
    with pytest.raises(ValueError, match="immutable"):
        extraction.persist_price_records(session, [record])


@pytest.mark.parametrize(
    "override",
    [
        {"unit": "unknown"},
        {"pricePerUnit": []},
        {"pricePerUnit": {"CNY": "1"}},
        {"pricePerUnit": {"USD": "NaN"}},
        {"pricePerUnit": {"USD": "-1"}},
        {"pricePerUnit": {"USD": "invalid"}},
        {"beginRange": "1"},
        {"endRange": "0"},
        {"endRange": "NaN"},
        {"endRange": ""},
        {"description": "Not a relevant rate"},
    ],
)
def test_invalid_price_dimensions_are_not_imported(price_input, override):
    snapshot, document, dimension = price_input
    dimension.update(override)
    assert (
        extraction._record_from_aws_s3_dimension(
            sku="SYNTHETIC",
            offer_term_code="offer",
            rate_code="rate",
            dimension=dimension,
            snapshot=snapshot,
            document=document,
        )
        is None
    )


def test_open_ended_tier_is_explicit_not_inferred(price_input):
    snapshot, document, dimension = price_input
    dimension["endRange"] = "Inf"
    result = extraction._record_from_aws_s3_dimension(
        sku="SYNTHETIC",
        offer_term_code="offer",
        rate_code="rate",
        dimension=dimension,
        snapshot=snapshot,
        document=document,
    )
    assert result.maximum_quantity is None
    dimension.pop("beginRange")
    assert (
        extraction._record_from_aws_s3_dimension(
            sku="SYNTHETIC",
            offer_term_code="offer",
            rate_code="rate",
            dimension=dimension,
            snapshot=snapshot,
            document=document,
        )
        is None
    )
