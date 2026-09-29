import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import huawei_promotion as promotion
from cloud_expert.pricing.api_capture import import_api_capture
from cloud_expert.pricing.domestic_readiness import generate_domestic_readiness
from cloud_expert.pricing.freshness import price_snapshot_freshness
from tests.fixtures.synthetic_data import load_synthetic_fixture
from tests.unit.test_huawei_api_capture import component_query, obs_query, price_query


@pytest.fixture
def promotion_input(session, tmp_path):
    fixture = load_synthetic_fixture(session)
    product = fixture["product"]
    product.provider.code = "huawei_cloud"
    product.code = "ecs"
    session.add(
        CloudPartition(
            provider_id=product.provider_id,
            partition_code="huawei_cn",
            partition_name="Synthetic partition",
            market_mode="domestic",
        )
    )
    session.flush()
    store = SnapshotStore(tmp_path / "raw")
    quote_path = tmp_path / "quote.json"
    quote_path.write_text(
        json.dumps(
            {
                "currency": "CNY",
                "product_rating_results": [
                    {"id": "synthetic-quote", "measure_id": 1, "official_website_amount": "1.25"}
                ],
            }
        )
    )
    at = datetime.now(UTC) - timedelta(days=2)
    quote = import_api_capture(
        session,
        get_entry_by_source_id("huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2"),
        quote_path,
        at,
        query=price_query(),
        store=store,
    )
    units_path = tmp_path / "units.json"
    units_path.write_text(
        json.dumps(
            {
                "measure_units": [
                    {"measure_id": mid, "abbreviation": abbr, "measure_type": kind}
                    for mid, abbr, kind in [(4, "h", 2), (10, "G", 3), (54, "TTM", 4)]
                ]
            }
        )
    )
    units = import_api_capture(
        session,
        get_entry_by_source_id("huawei_cloud_billing_measurements_api"),
        units_path,
        at,
        store=store,
    )
    entry = get_entry_by_source_id(promotion.TAX_SOURCE)
    raw = f"<article><p>{promotion.TAX_SENTENCE}</p></article>".encode()
    stored = store.store(
        entry=entry,
        requested_url=entry.url,
        final_url=entry.url,
        http_status=200,
        content_type="text/html",
        content=raw,
        response_headers={},
        content_metadata={},
        fetch_duration_ms=0,
        captured_at=at,
    )
    document = SourceDocument(
        provider_id=product.provider_id,
        source_type="documentation",
        title="Synthetic tax policy fixture",
        url=entry.url,
        cloud_partition="huawei_cn",
        authority_level="official_primary",
        content_hash=sha256(raw).hexdigest(),
        is_current=True,
    )
    session.add(document)
    session.flush()
    snapshot = SnapshotRecord(
        source_document_id=document.id,
        source_id=entry.source_id,
        content_hash=document.content_hash,
        storage_path=stored.manifest.storage_path,
        manifest_path=str(stored.manifest_path.relative_to(store.raw_data_dir)),
        content_type="text/html",
        content_length_bytes=len(raw),
        captured_at=at,
        change_status="first_seen",
        is_current=True,
    )
    session.add(snapshot)
    session.flush()
    tax = promotion.extract_tax_policy(session, root=store.raw_data_dir)
    return quote["evidence_ids"][0], units["evidence_ids"], tax.id, store


def test_promote_exact_quote_idempotently_and_keep_capture_time(session, promotion_input):
    quote, units, tax, store = promotion_input
    result = promotion.promote_quote(session, quote, units[0], tax, root=store.raw_data_dir)
    price = session.get(PriceSnapshot, result["price_snapshot_id"])
    assert price.unit_price == Decimal("1.25")
    assert price.minimum_quantity == price.maximum_quantity == Decimal(1)
    assert price.price_sku.tax_included is True
    assert price.price_sku.sku_id is None
    assert price.captured_at.date() < datetime.now(UTC).date()
    assert promotion.bounded_quote_valid(session, price, root=store.raw_data_dir)
    again = promotion.promote_quote(session, quote, units[0], tax, root=store.raw_data_dir)
    assert not again["created"]
    assert again["price_snapshot_id"] == price.id


@pytest.mark.parametrize(
    "change",
    [
        "quote_hash",
        "raw_hash",
        "tax_rejected",
        "wrong_unit",
        "not_current",
        "wrong_market",
        "price_changed",
        "quantity_changed",
        "tax_changed",
        "capture_time_changed",
        "manifest_query_changed",
    ],
)
def test_promotion_or_consumption_rejects_invalid_support(session, promotion_input, change):
    quote, units, tax, store = promotion_input
    result = promotion.promote_quote(session, quote, units[0], tax, root=store.raw_data_dir)
    price = session.get(PriceSnapshot, result["price_snapshot_id"])
    evidence = session.get(Evidence, quote)
    snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
    if change == "quote_hash":
        evidence.excerpt += " altered"
    elif change == "raw_hash":
        (store.raw_data_dir / snapshot.storage_path).write_bytes(b"altered")
    elif change == "tax_rejected":
        session.get(Evidence, tax).review_status = "rejected"
    elif change == "wrong_unit":
        with pytest.raises(ValueError, match="unit evidence"):
            promotion.promote_quote(session, quote, units[1], tax, root=store.raw_data_dir)
        return
    elif change == "not_current":
        snapshot.is_current = False
    elif change == "wrong_market":
        price.price_sku.region.market_mode = "international"
    elif change == "price_changed":
        price.unit_price = Decimal("3.50")
    elif change == "quantity_changed":
        price.maximum_quantity = Decimal(730)
    elif change == "capture_time_changed":
        price.captured_at += timedelta(hours=1)
    elif change == "manifest_query_changed":
        path = store.raw_data_dir / snapshot.manifest_path
        manifest = json.loads(path.read_text())
        manifest["content_metadata"]["request"]["product_infos"][0]["usage_value"] = 730
        path.write_text(json.dumps(manifest))
    else:
        price.price_sku.tax_included = False
    assert not promotion.bounded_quote_valid(session, price, root=store.raw_data_dir)


def test_storage_quote_stays_quarantined(session, promotion_input, tmp_path):
    _, units, tax, store = promotion_input
    query = obs_query()
    path = tmp_path / "obs.json"
    path.write_text(
        json.dumps(
            {
                "currency": "CNY",
                "product_rating_results": [
                    {"id": item.id, "measure_id": 1, "official_website_amount": "7.5"}
                    for item in query.product_infos
                ],
            }
        )
    )
    result = import_api_capture(
        session,
        get_entry_by_source_id("huawei_cloud_obs_pricing_api_cn_north_4"),
        path,
        datetime.now(UTC),
        query=query,
        store=store,
    )
    with pytest.raises(ValueError, match="billing period"):
        promotion.promote_quote(
            session, result["evidence_ids"][0], units[1], tax, root=store.raw_data_dir
        )


@pytest.mark.parametrize("field", ["captured_at", "effective_from"])
def test_future_dated_price_is_not_fresh(field):
    now = datetime.now(UTC)
    price = PriceSnapshot(captured_at=now)
    setattr(price, field, now + timedelta(hours=1))
    assert price_snapshot_freshness(price, now=now) == "unknown"


def test_tax_policy_missing_statement_is_rejected(session, promotion_input):
    _, _, _, store = promotion_input
    snapshot = session.scalar(
        select(SnapshotRecord).where(SnapshotRecord.source_id == promotion.TAX_SOURCE)
    )
    raw = b"<p>Synthetic policy without tax inclusion.</p>"
    (store.raw_data_dir / snapshot.storage_path).write_bytes(raw)
    snapshot.content_hash = sha256(raw).hexdigest()
    snapshot.source_document.content_hash = snapshot.content_hash
    with pytest.raises(ValueError, match="not found"):
        promotion.extract_tax_policy(session, root=store.raw_data_dir)


def test_domestic_readiness_uses_exact_quantity_and_preserves_missing_costs(
    session, promotion_input, tmp_path, monkeypatch
):
    quote, units, tax, store = promotion_input
    monkeypatch.setattr(
        promotion, "get_settings", lambda: SimpleNamespace(raw_data_dir=store.raw_data_dir)
    )
    promotion.promote_quote(session, quote, units[0], tax, root=store.raw_data_dir)
    missing = generate_domestic_readiness(session)["runs"][0]
    assert missing["results"][0]["total"] is None
    assert all(item["amount"] is None for item in missing["line_items"])
    query = price_query()
    query.product_infos[0].usage_value = 730
    path = tmp_path / "monthly_quote.json"
    path.write_text(
        json.dumps(
            {
                "currency": "CNY",
                "product_rating_results": [
                    {"id": "synthetic-quote", "measure_id": 1, "official_website_amount": "912.50"}
                ],
            }
        )
    )
    monthly = import_api_capture(
        session,
        get_entry_by_source_id("huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2_730h"),
        path,
        datetime.now(UTC),
        query=query,
        store=store,
    )
    promotion.promote_quote(
        session, monthly["evidence_ids"][0], units[0], tax, root=store.raw_data_dir
    )
    result = generate_domestic_readiness(session)["runs"][0]
    assert result["currency"] == "CNY"
    assert result["results"][0]["status"] == "missing_price"
    assert result["results"][0]["total"] is None
    assert Decimal(result["results"][0]["known_subtotal"]) == Decimal("912.50")
    assert sum(item["amount"] is not None for item in result["line_items"]) == 1
    assert not result["customer_eligible"]
    repeated = generate_domestic_readiness(session)["runs"][0]
    assert not repeated["created"]
    assert repeated["run_id"] == result["run_id"]
    session.get(Evidence, tax).review_status = "rejected"
    invalidated = generate_domestic_readiness(session)["runs"][0]
    assert invalidated["results"][0]["known_subtotal"] is None


@pytest.fixture
def component_input(session, promotion_input, tmp_path):
    _, units, tax, store = promotion_input
    query = component_query()
    amounts = {"compute": "1095.00", "disk": "73.00", "traffic": "83.00", "ip": "21.90"}
    path = tmp_path / "components.json"
    path.write_text(
        json.dumps(
            {
                "currency": "CNY",
                "product_rating_results": [
                    {"id": item.id, "measure_id": 1, "official_website_amount": amounts[item.id]}
                    for item in query.product_infos
                ],
            }
        )
    )
    at = datetime.now(UTC)
    result = import_api_capture(
        session,
        get_entry_by_source_id("huawei_cloud_ecs_pricing_api_cn_north_4_components_730h"),
        path,
        at,
        query=query,
        store=store,
    )
    entry = get_entry_by_source_id("huawei_cloud_pricing_api_parameters")
    raw = "<ul><li>15：Mbps</li><li>17：GB</li></ul>".encode()
    stored = store.store(
        entry=entry,
        requested_url=entry.url,
        final_url=entry.url,
        http_status=200,
        content_type="text/html",
        content=raw,
        response_headers={},
        content_metadata={},
        fetch_duration_ms=0,
        captured_at=at,
    )
    document = SourceDocument(
        provider_id=session.get(Evidence, tax).source_document.provider_id,
        source_type="documentation",
        title="Synthetic component unit policy",
        url=entry.url,
        cloud_partition="huawei_cn",
        authority_level="official_primary",
        content_hash=sha256(raw).hexdigest(),
        captured_at=at,
        is_current=True,
    )
    session.add(document)
    session.flush()
    snapshot = SnapshotRecord(
        source_document_id=document.id,
        source_id=entry.source_id,
        content_hash=document.content_hash,
        storage_path=stored.manifest.storage_path,
        manifest_path=str(stored.manifest_path.relative_to(store.raw_data_dir)),
        content_type="text/html",
        content_length_bytes=len(raw),
        captured_at=at,
        change_status="first_seen",
        is_current=True,
    )
    session.add(snapshot)
    session.flush()
    size_ids = []
    for index, clause in enumerate(promotion.extract_clauses(entry.source_id, raw.decode())):
        row = promotion._get_or_create_evidence(
            session,
            snapshot,
            f"synthetic:clause{index}",
            json.dumps(clause, ensure_ascii=False, sort_keys=True),
            "supporting_price_policy_v1",
        )
        size_ids.append(row.id)
    return result["evidence_ids"], units, tax, size_ids, store


@pytest.mark.parametrize("component", [0, 1, 2])
def test_component_promotion_preserves_exact_scope(session, component_input, component):
    quotes, units, tax, sizes, store = component_input
    size_id = sizes[1] if component == 1 else sizes[0] if component == 2 else None
    result = promotion.promote_quote(
        session,
        quotes[component],
        units[1 if component == 2 else 0],
        tax,
        size_evidence_id=size_id,
        root=store.raw_data_dir,
    )
    price = session.get(PriceSnapshot, result["price_snapshot_id"])
    expected = [("instance-hour", "730", "1095"), ("GB-hour", "73000", "73"), ("GB", "100", "83")]
    unit, quantity, amount = expected[component]
    assert price.price_sku.billing_unit == unit
    assert price.minimum_quantity == price.maximum_quantity == Decimal(quantity)
    assert price.unit_price * Decimal(quantity) == Decimal(amount)
    assert promotion.bounded_quote_valid(session, price, root=store.raw_data_dir)
    repeated = promotion.promote_quote(
        session,
        quotes[component],
        units[1 if component == 2 else 0],
        tax,
        size_evidence_id=size_id,
        root=store.raw_data_dir,
    )
    assert not repeated["created"]
    if size_id is not None:
        session.get(Evidence, size_id).review_status = "rejected"
        assert not promotion.bounded_quote_valid(session, price, root=store.raw_data_dir)


@pytest.mark.parametrize("component", [1, 2, 3])
def test_components_cannot_reuse_vm_duration_without_scope(session, component_input, component):
    quotes, units, tax, _, store = component_input
    with pytest.raises(ValueError):
        promotion.promote_quote(session, quotes[component], units[0], tax, root=store.raw_data_dir)


def test_disk_rejects_bandwidth_size_evidence(session, component_input):
    quotes, units, tax, sizes, store = component_input
    with pytest.raises(ValueError, match="size evidence"):
        promotion.promote_quote(
            session,
            quotes[1],
            units[0],
            tax,
            size_evidence_id=sizes[0],
            root=store.raw_data_dir,
        )
