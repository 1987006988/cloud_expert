import json
from datetime import UTC, datetime, timedelta

import pytest

from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing.api_capture import (
    COMPONENT_SCOPE,
    COMPONENT_SOURCE,
    _validate_quote_scope,
    import_api_capture,
)
from cloud_expert.pricing.huawei_api import PricingQuery


def price_query():
    return PricingQuery.model_validate(
        {
            "product_infos": [
                {
                    "id": "synthetic-quote",
                    "cloud_service_type": "hws.service.type.ec2",
                    "resource_type": "hws.resource.type.vm",
                    "resource_spec": "c6.large.2.linux",
                    "region": "cn-north-4",
                    "usage_factor": "Duration",
                    "usage_value": 1,
                    "usage_measure_id": 4,
                    "subscription_num": 1,
                }
            ]
        }
    )


def component_query():
    fields = (
        "cloud_service_type",
        "resource_type",
        "resource_spec",
        "usage_factor",
        "usage_value",
        "usage_measure_id",
        "resource_size",
        "size_measure_id",
    )
    return PricingQuery.model_validate(
        {
            "product_infos": [
                {
                    "id": key,
                    "region": "cn-north-4",
                    "subscription_num": 1,
                    **dict(zip(fields, values, strict=True)),
                }
                for key, values in COMPONENT_SCOPE.items()
            ]
        }
    )


def test_component_scope_and_quarantined_import(session, tmp_path):
    entry = get_entry_by_source_id(COMPONENT_SOURCE)
    query = component_query()
    _validate_quote_scope(entry, query)
    for field, value in (("region", "cn-east-3"), ("resource_size", 101), ("usage_value", 731)):
        changed = query.model_copy(deep=True)
        setattr(changed.product_infos[1], field, value)
        with pytest.raises(ValueError, match="scope"):
            _validate_quote_scope(entry, changed)
    incomplete = query.model_copy(deep=True)
    incomplete.product_infos.pop()
    with pytest.raises(ValueError, match="IDs"):
        _validate_quote_scope(entry, incomplete)
    path = tmp_path / "synthetic-components.json"
    path.write_text(
        json.dumps(
            {
                "currency": "CNY",
                "product_rating_results": [
                    {"id": item.id, "measure_id": 1, "official_website_amount": "987.65"}
                    for item in query.product_infos
                ],
            }
        )
    )
    result = import_api_capture(
        session, entry, path, datetime.now(UTC), query=query, store=SnapshotStore(tmp_path / "raw")
    )
    assert len(result["evidence_ids"]) == 4
    assert result["price_skus_created"] == result["price_snapshots_created"] == 0
    disk = json.loads(session.get(Evidence, result["evidence_ids"][1]).excerpt)
    assert disk["request"]["resource_size"] == 100
    assert disk["quantity_scope"] == "quoted_quantity_only"


def test_hourly_and_monthly_quote_scopes_are_not_interchangeable():
    hourly = get_entry_by_source_id("huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2")
    monthly = get_entry_by_source_id("huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2_730h")
    query = price_query()
    _validate_quote_scope(hourly, query)
    with pytest.raises(ValueError, match="scope"):
        _validate_quote_scope(monthly, query)
    query.product_infos[0].usage_value = 730
    _validate_quote_scope(monthly, query)
    with pytest.raises(ValueError, match="scope"):
        _validate_quote_scope(hourly, query)
    monthly.source_id = "unregistered_ecs_source"
    with pytest.raises(ValueError, match="unregistered"):
        _validate_quote_scope(monthly, query)


def test_controlled_price_capture_and_idempotence(session, tmp_path):
    entry = get_entry_by_source_id("huawei_cloud_ecs_pricing_api_cn_north_4_c6_large_2")
    response = {
        "currency": "CNY",
        "product_rating_results": [
            {
                "id": "synthetic-quote",
                "official_website_amount": "1.25",
                "measure_id": 1,
                "discount_name": "SYNTHETIC_PRIVATE_ACCOUNT_DISCOUNT",
            }
        ],
    }
    path = tmp_path / "synthetic_response.json"
    path.write_text(json.dumps(response))
    store = SnapshotStore(tmp_path / "raw")
    at = datetime.now(UTC)
    first = import_api_capture(session, entry, path, at, query=price_query(), store=store)
    second = import_api_capture(session, entry, path, at, query=price_query(), store=store)
    assert first["evidence_ids"] == second["evidence_ids"]
    assert first["snapshot_record_id"] == second["snapshot_record_id"]
    assert not second["snapshot_created"]
    assert first["price_skus_created"] == first["price_snapshots_created"] == 0
    evidence = session.get(Evidence, first["evidence_ids"][0])
    assert "SYNTHETIC_PRIVATE_ACCOUNT_DISCOUNT" not in evidence.excerpt
    assert '"tax_status": "unverified"' in evidence.excerpt
    assert (
        store.raw_data_dir / store.latest_manifest(entry)[0].storage_path
    ).read_bytes() == path.read_bytes()
    assert (
        store.latest_manifest(entry)[0].content_metadata["wire_response_bytes_available"] is False
    )
    with pytest.raises(ValueError, match="scope"):
        different = price_query()
        different.product_infos[0].region = "cn-east-3"
        import_api_capture(session, entry, path, at, query=different, store=store)
    with pytest.raises(ValueError, match="one scoped"):
        different = price_query()
        different.product_infos.append(different.product_infos[0])
        import_api_capture(session, entry, path, at, query=different, store=store)


def test_measurement_capture(session, tmp_path):
    entry = get_entry_by_source_id("huawei_cloud_billing_measurements_api")
    path = tmp_path / "units.json"
    path.write_text(
        json.dumps(
            {
                "measure_units": [
                    {
                        "measure_id": 4,
                        "measure_name": "synthetic hour",
                        "abbreviation": "h",
                        "measure_type": 2,
                    },
                ]
            }
        )
    )
    result = import_api_capture(
        session, entry, path, datetime.now(UTC), store=SnapshotStore(tmp_path / "raw")
    )
    evidence = session.get(Evidence, result["evidence_ids"][0])
    assert evidence.locator == "json:$.measure_units[0]"
    assert "synthetic hour" in evidence.excerpt


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"measure_units": []},
        {"measure_units": [42]},
        {"measure_units": [{"measure_id": 4, "abbreviation": "bad"}]},
    ],
)
def test_invalid_measurement_capture_rejected(session, tmp_path, payload):
    entry = get_entry_by_source_id("huawei_cloud_billing_measurements_api")
    path = tmp_path / "units.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        import_api_capture(
            session, entry, path, datetime.now(UTC), store=SnapshotStore(tmp_path / "raw")
        )
    assert not (tmp_path / "raw").exists()


def test_unapproved_source_timestamp_size_and_endpoint_rejected(session, tmp_path):
    entry = get_entry_by_source_id("huawei_cloud_billing_measurements_api")
    path = tmp_path / "units.json"
    path.write_text("{}")
    kwargs = {"store": SnapshotStore(tmp_path / "raw")}
    for at in (datetime.now(), datetime.now(UTC) + timedelta(days=1)):
        with pytest.raises(ValueError, match="timestamp"):
            import_api_capture(session, entry, path, at, **kwargs)
    entry.terms_review_status = "disallowed"
    with pytest.raises(ValueError, match="not approved"):
        import_api_capture(session, entry, path, datetime.now(UTC), **kwargs)
    entry.terms_review_status = "approved"
    entry.url = "https://bss.myhuaweicloud.com/unsupported"
    with pytest.raises(ValueError, match="unsupported"):
        import_api_capture(session, entry, path, datetime.now(UTC), **kwargs)
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="size"):
        import_api_capture(session, entry, path, datetime.now(UTC), **kwargs)


def obs_query():
    return PricingQuery.model_validate(
        {
            "product_infos": [
                {
                    "id": f"synthetic-{factor}",
                    "cloud_service_type": "hws.service.type.obs",
                    "resource_type": "hws.resource.type.obs",
                    "resource_spec": "obs",
                    "region": "cn-north-4",
                    "usage_factor": factor,
                    "usage_value": value,
                    "usage_measure_id": unit,
                    "subscription_num": 1,
                }
                for factor, value, unit in [
                    ("size", 1024, 10),
                    ("get", 1, 54),
                    ("put", 1, 54),
                    ("download.external", 100, 10),
                ]
            ]
        }
    )


def test_obs_capture_correlates_by_id_and_keeps_period_unknown(session, tmp_path):
    entry = get_entry_by_source_id("huawei_cloud_obs_pricing_api_cn_north_4")
    query = obs_query()
    response = {
        "currency": "CNY",
        "product_rating_results": [
            {"id": item.id, "official_website_amount": "9.99", "measure_id": 1}
            for item in reversed(query.product_infos)
        ],
    }
    path = tmp_path / "synthetic_obs.json"
    path.write_text(json.dumps(response))
    at = datetime.now(UTC)
    store = SnapshotStore(tmp_path / "raw")
    result = import_api_capture(session, entry, path, at, query=query, store=store)
    assert len(result["evidence_ids"]) == 4
    assert "storage_billing_period" in result["remaining_checks"]
    for evidence_id in result["evidence_ids"]:
        evidence = session.get(Evidence, evidence_id)
        excerpt = json.loads(evidence.excerpt)
        factor = excerpt["request"]["usage_factor"]
        assert excerpt["billing_period_status"] == (
            "unverified" if factor == "size" else "usage_based"
        )
        assert excerpt["quantity_scope"] == "quoted_quantity_only"
    repeated = import_api_capture(session, entry, path, at, query=query, store=store)
    assert repeated["evidence_ids"] == result["evidence_ids"]
    query.product_infos.reverse()
    with pytest.raises(ValueError, match="different query"):
        import_api_capture(session, entry, path, at, query=query, store=store)


@pytest.mark.parametrize("change", ["unit", "factor", "quantity", "zone", "precision", "currency"])
def test_obs_capture_rejects_scope_change(session, tmp_path, change):
    entry = get_entry_by_source_id("huawei_cloud_obs_pricing_api_cn_north_4")
    query = obs_query()
    response = {
        "currency": "CNY",
        "product_rating_results": [
            {"id": item.id, "official_website_amount": "9.99", "measure_id": 1}
            for item in query.product_infos
        ],
    }
    if change == "unit":
        query.product_infos[0].usage_measure_id = 17
    elif change == "factor":
        query.product_infos[0].usage_factor = "get"
    elif change == "quantity":
        query.product_infos[0].usage_value = 2048
    elif change == "zone":
        query.product_infos[0].available_zone = "synthetic-zone"
    elif change == "precision":
        query.inquiry_precision = 0
    else:
        response.pop("currency")
    path = tmp_path / "synthetic_obs.json"
    path.write_text(json.dumps(response))
    with pytest.raises(ValueError):
        import_api_capture(
            session,
            entry,
            path,
            datetime.now(UTC),
            query=query,
            store=SnapshotStore(tmp_path / "raw"),
        )
    assert not (tmp_path / "raw").exists()


def test_obs_measurement_dictionary_and_duplicate_rejection(session, tmp_path):
    entry = get_entry_by_source_id("huawei_cloud_billing_measurements_api")
    rows = [
        {"measure_id": mid, "abbreviation": abbreviation, "measure_type": kind}
        for mid, abbreviation, kind in [(4, "h", 2), (10, "G", 3), (54, "TTM", 4)]
    ]
    path = tmp_path / "units.json"
    path.write_text(json.dumps({"measure_units": rows}))
    store = SnapshotStore(tmp_path / "raw")
    result = import_api_capture(session, entry, path, datetime.now(UTC), store=store)
    assert len(result["evidence_ids"]) == 3
    rows.append(rows[-1])
    path.write_text(json.dumps({"measure_units": rows}))
    with pytest.raises(ValueError, match="duplicated"):
        import_api_capture(session, entry, path, datetime.now(UTC), store=store)
