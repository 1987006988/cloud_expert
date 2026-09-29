import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing.aliyun_capture import SOURCE_ID, import_catalog, inspect_catalog
from tests.fixtures.synthetic_data import load_synthetic_fixture


def make_catalog():
    now = datetime.now(UTC)
    return {
        "schema_version": 1,
        "source_code": SOURCE_ID,
        "capture_method": "browser_rendered_dom_bundle",
        "sections": [
            {
                "section": name,
                "captured_at": (now - timedelta(minutes=3 - i)).isoformat(),
                "url": "https://www.aliyun.com/price/product#/ecs/detail/vm",
                "region_html": '<button value="cn-beijing" '
                'class="ant-radio-button-wrapper-checked">Synthetic region selection</button>',
                "page_ax": "Synthetic fixture. 非实时价格; 不关联个人优惠",
                "tables": [
                    "<table><thead><tr><th>Synthetic item</th><th>Price</th></tr></thead>"
                    "<tbody><tr><td>Not a real product</td><td>￥987.654</td></tr></tbody></table>"
                ],
            }
            for i, name in enumerate(("compute", "disk", "network"))
        ],
    }


@pytest.fixture
def catalog():
    return make_catalog()


def test_catalog_preserves_limits_and_earliest_capture(catalog):
    captured, records = inspect_catalog(json.dumps(catalog).encode())
    assert captured.isoformat() == catalog["sections"][0]["captured_at"]
    assert len(records) == 3
    assert records[0]["headers"] == ["Synthetic item", "Price"]
    assert all(r["tax_status"] == "unverified" and not r["realtime"] for r in records)
    assert all(not r["customer_quote_eligible"] for r in records)


@pytest.mark.parametrize(
    "change",
    [
        {"url": "https://evil.example/price/product#/ecs/detail"},
        {"url": "https://www.aliyun.com/price/product#/oss/detail"},
        {"region_html": '<button value="cn-beijing">not selected</button>'},
        {"page_ax": "No limitations preserved"},
        {"tables": ["<table></table>"]},
        {"tables": ["not a table"]},
        {"captured_at": "2099-01-01T00:00:00Z"},
        {"captured_at": "2026-01-01T00:00:00"},
    ],
)
def test_catalog_rejects_unproven_capture(catalog, change):
    catalog["sections"][0].update(change)
    with pytest.raises(ValueError):
        inspect_catalog(json.dumps(catalog).encode())


def test_catalog_rejects_wrong_schema_and_missing_sections(catalog):
    modified = deepcopy(catalog)
    modified["schema_version"] = 9
    with pytest.raises(ValueError, match="format"):
        inspect_catalog(json.dumps(modified).encode())
    catalog["sections"].pop()
    with pytest.raises(ValueError, match="sections"):
        inspect_catalog(json.dumps(catalog).encode())


def test_controlled_import_is_idempotent_and_does_not_promote(session, tmp_path, catalog):
    fixture = load_synthetic_fixture(session)
    fixture["product"].provider.code = "aliyun"
    session.flush()
    entry = next(e for e in load_registry_entries() if e.source_id == SOURCE_ID)
    path = tmp_path / "browser.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    store = SnapshotStore(tmp_path / "raw")
    first = import_catalog(session, entry, path, store=store)
    assert first["snapshot_created"]
    assert len(first["evidence_ids"]) == 3
    assert first["price_skus_created"] == first["price_snapshots_created"] == 0
    assert not first["customer_output_eligible"]
    count = session.scalar(select(func.count()).select_from(Evidence))
    second = import_catalog(session, entry, path, store=store)
    assert not second["snapshot_created"]
    assert second["evidence_ids"] == first["evidence_ids"]
    assert session.scalar(select(func.count()).select_from(Evidence)) == count
    document = session.get(SourceDocument, first["source_document_id"])
    assert document.http_status is None
    for section in catalog["sections"]:
        section["captured_at"] = "2020-01-01T00:00:00Z"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="older capture"):
        import_catalog(session, entry, path, store=store)
    with pytest.raises(ValueError, match="not approved"):
        import_catalog(session, entry.model_copy(update={"terms_review_status": "pending"}), path)
