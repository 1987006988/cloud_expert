import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import select

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.tco import CostCalculationRun, PricingScenario
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import aliyun_promotion as promotion
from cloud_expert.pricing import extraction
from cloud_expert.pricing.aliyun_capture import import_catalog
from cloud_expert.pricing.tco import (
    WorkloadDimension,
    _line_item_for_dimension,
    _results_from_line_items,
    tco_result_currently_complete,
)
from tests.fixtures.synthetic_data import load_synthetic_fixture
from tests.unit.test_aliyun_browser_catalog import make_catalog


@pytest.fixture
def inputs(session, tmp_path, monkeypatch):
    catalog = make_catalog()
    fixture = load_synthetic_fixture(session)
    product = fixture["product"]
    product.provider.code, product.code = "aliyun", "ecs"
    partition = CloudPartition(
        provider_id=product.provider_id,
        partition_code="aliyun_public_cn",
        partition_name="Synthetic China",
        market_mode="domestic",
    )
    session.add(partition)
    session.flush()
    fixture["region"].code = "cn-beijing"
    fixture["region"].cloud_partition_id = partition.id
    specs = [
        (
            [
                "实例规格",
                "vCPUs",
                "内存(GiB)",
                "按量目录价",
                "包月目录价",
                "包周价格",
                "按量月价(30天)",
            ],
            ["通用型 ecs.g6.xlarge", "4", "16", "￥2.5", "￥999", "￥333", "￥1800"],
        ),
        (
            ["类别", "最大IOPS/最大吞吐量", "云盘容量范围（GiB）", "按量价格 ( 元/GiB/小时 )"],
            ["ESSD PL1云盘", "Synthetic performance", "20 ~ 65,536 GiB", "￥0.003"],
        ),
        (["计费方式", "类型", "价格"], ["按使用量线性计费", "1GB", "￥0.95/GB"]),
    ]
    for section, (headers, cells) in zip(catalog["sections"], specs, strict=True):
        section["tables"] = [
            "<table><thead><tr>"
            + "".join(f"<th>{h}</th>" for h in headers)
            + "</tr></thead><tbody><tr>"
            + "".join(f"<td>{v}</td>" for v in cells)
            + "</tr></tbody></table>"
        ]
    store = SnapshotStore(tmp_path / "raw")
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    result = import_catalog(
        session, get_entry_by_source_id("aliyun_ecs_pricing"), path, store=store
    )
    raw = (
        "<table><tr><th>差异点</th><th>阿里云中国站 (www.aliyun.com)</th><th>Intl</th></tr>"
        "<tr><td>交易货币</td><td>CNY</td><td>USD</td></tr>"
        "<tr><td>价格说明</td><td>价格包含增值税。</td><td>Excluded</td></tr></table>"
    ).encode()
    entry = get_entry_by_source_id(promotion.TAX_SOURCE)
    at = datetime.now(UTC)
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
    doc = SourceDocument(
        provider_id=product.provider_id,
        title="Synthetic policy",
        source_type="documentation",
        url=entry.url,
        cloud_partition="aliyun_public_cn",
        authority_level="official_primary",
        content_hash=sha256(raw).hexdigest(),
        captured_at=at,
        is_current=True,
    )
    session.add(doc)
    session.flush()
    snap = SnapshotRecord(
        source_document_id=doc.id,
        source_id=entry.source_id,
        content_hash=doc.content_hash,
        storage_path=stored.manifest.storage_path,
        manifest_path=str(stored.manifest_path.relative_to(store.raw_data_dir)),
        content_type="text/html",
        content_length_bytes=len(raw),
        captured_at=at,
        change_status="first_seen",
        is_current=True,
    )
    session.add(snap)
    session.flush()
    excerpt = json.dumps(
        promotion.extract_clauses(entry.source_id, raw.decode())[0], ensure_ascii=False
    )
    tax = Evidence(
        source_document_id=doc.id,
        snapshot_record_id=snap.id,
        locator="synthetic:tax",
        excerpt=excerpt,
        content_hash=sha256(excerpt.encode()).hexdigest(),
        evidence_type="html_section",
        parser_rule="supporting_price_policy_v1",
        confidence=1.0,
        review_status="machine_extracted",
    )
    session.add(tax)
    session.flush()
    monkeypatch.setattr(extraction, "_raw_data_dir", lambda: store.raw_data_dir)
    return result["evidence_ids"], tax.id, store


def test_bounded_estimates_preserve_catalog_limits_and_are_idempotent(session, inputs):
    ids, tax, _ = inputs
    records = [promotion.extract_catalog_record(session, eid, tax) for eid in ids]
    assert [r.unit_price for r in records] == [Decimal("2.5"), Decimal("0.003"), Decimal("0.95")]
    assert [r.minimum_quantity for r in records] == [Decimal(720), Decimal(72000), Decimal(100)]
    assert all(
        r.minimum_quantity == r.maximum_quantity and r.discount_type == "estimated" for r in records
    )
    assert extraction.persist_price_records(session, records)["created_price_snapshots"] == 3
    assert extraction.persist_price_records(session, records)["created_price_snapshots"] == 0
    prices = list(
        session.scalars(
            select(PriceSnapshot).where(PriceSnapshot.evidence.has(parser_rule=promotion.RULE))
        )
    )
    assert len(prices) == 3
    assert all(promotion.catalog_price_valid(session, p) for p in prices)
    assert all(not json.loads(p.evidence.excerpt)["customer_approved"] for p in prices)
    session.get(Evidence, tax).review_status = "rejected"
    assert all(not promotion.catalog_price_valid(session, p) for p in prices)


@pytest.mark.parametrize("change", ["raw", "excerpt", "tax", "market", "quantity", "period"])
def test_catalog_promotion_rechecks_mutations(session, inputs, change):
    ids, tax_id, store = inputs
    record = promotion.extract_catalog_record(session, ids[0], tax_id)
    extraction.persist_price_records(session, [record])
    price = session.scalar(
        select(PriceSnapshot).where(PriceSnapshot.evidence.has(parser_rule=promotion.RULE))
    )
    source = session.get(Evidence, ids[0])
    if change == "raw":
        snap = session.get(SnapshotRecord, source.snapshot_record_id)
        (store.raw_data_dir / snap.storage_path).write_bytes(b"tampered")
    elif change == "excerpt":
        source.excerpt = "{}"
        source.content_hash = sha256(source.excerpt.encode()).hexdigest()
    elif change == "tax":
        session.get(Evidence, tax_id).source_document.cloud_partition = "aliyun_intl"
    elif change == "market":
        price.price_sku.region.market_mode = "international"
    elif change == "quantity":
        price.maximum_quantity = Decimal(730)
    else:
        price.billing_period = "monthly"
    assert not promotion.catalog_price_valid(session, price)


def test_catalog_tco_requires_explicit_reference_only_scope(session, inputs):
    ids, tax, _ = inputs
    extraction.persist_price_records(
        session, [promotion.extract_catalog_record(session, ids[0], tax)]
    )
    price = session.scalar(
        select(PriceSnapshot).where(PriceSnapshot.evidence.has(parser_rule=promotion.RULE))
    )
    scenario = PricingScenario(
        scenario_code="synthetic_catalog",
        scenario_version="test",
        name="Synthetic only",
        market_mode="domestic",
        billing_period="30days",
        target_currency="CNY",
        workload_profile={"required_cost_dimensions": ["compute"]},
        assumptions={"tax_scope": "tax_included"},
        status="active",
    )
    session.add(scenario)
    session.flush()
    run = CostCalculationRun(
        scenario_id=scenario.id,
        run_code="synthetic_catalog",
        rule_version="test",
        price_snapshot_cutoff=datetime.now(UTC),
        started_at=datetime.now(UTC),
        status="succeeded",
        currency="CNY",
        provider_count=1,
        line_item_count=1,
        warning_count=0,
        error_count=0,
        content_hash="synthetic",
    )
    session.add(run)
    session.flush()
    item = _line_item_for_dimension(
        run=run,
        provider=price.price_sku.provider,
        product=price.price_sku.product,
        dimension=WorkloadDimension(
            "ecs", "compute", Decimal(720), "instance-hour", "instance-hour"
        ),
        snapshot=price,
    )
    session.add(item)
    session.flush()
    result = _results_from_line_items(run, scenario, [item])[0]
    session.add(result)
    session.flush()
    assert not tco_result_currently_complete(session, result)
    scenario.assumptions = {"tax_scope": "tax_included", "price_basis": "catalog_reference"}
    assert tco_result_currently_complete(session, result)
    price.maximum_quantity = Decimal(730)
    assert not tco_result_currently_complete(session, result)
