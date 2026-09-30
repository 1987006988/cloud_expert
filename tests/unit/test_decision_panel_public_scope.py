"""Synthetic detached evidence only; no business DB, model calls or report writes."""

import hashlib
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.model_review import decision_panel as panel
from cloud_expert.pricing import aliyun_promotion, extraction, supporting_policies
from cloud_expert.pricing.aliyun_capture import RULE as CAPTURE_RULE
from cloud_expert.pricing.aliyun_capture import inspect_catalog
from tests.unit.test_aliyun_browser_catalog import make_catalog


def _digest(value):
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def public_scope(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    entries = {
        source: get_entry_by_source_id(source).model_copy(
            update={"reviewed_at": now - timedelta(days=1)}
        )
        for source in (aliyun_promotion.TAX_SOURCE, aliyun_promotion.SOURCE_ID)
    }
    monkeypatch.setattr(panel, "get_entry_by_source_id", entries.get)
    monkeypatch.setattr(aliyun_promotion, "get_entry_by_source_id", entries.get)
    monkeypatch.setattr(extraction, "_raw_data_dir", lambda: tmp_path)
    provider = Provider(id=1, code="aliyun", provider_type="fixture")
    product = Product(id=1, code="ecs", provider=provider, provider_id=1, market_mode="domestic")
    region = Region(
        id=1,
        provider_id=1,
        code="cn-beijing",
        country_code="CN",
        market_mode="domestic",
        cloud_partition=CloudPartition(partition_code="aliyun_public_cn"),
    )
    objects = {}
    session = Mock(new=set(), dirty=set(), deleted=set(), no_autoflush=nullcontext())
    session.get.side_effect = lambda cls, pk: objects.get((cls, pk))
    session.scalar.side_effect = lambda statement: (
        product if statement.column_descriptions[0]["entity"] is Product else region
    )

    def source(source_id, sid, eid, raw, excerpt, rule, locator, captured):
        entry = entries[source_id]
        path = tmp_path / f"synthetic_{sid}.bin"
        path.write_bytes(raw)
        document = SourceDocument(
            id=sid,
            provider=provider,
            provider_id=1,
            source_type=entry.source_type,
            title="SYNTHETIC ONLY",
            url=entry.url,
            authority_level="official_primary",
            cloud_partition="aliyun_public_cn",
            captured_at=captured,
            is_current=True,
            content_hash=_digest(raw),
        )
        snapshot = SnapshotRecord(
            id=sid,
            source_document_id=sid,
            source_document=document,
            source_id=source_id,
            content_hash=document.content_hash,
            storage_path=path.name,
            captured_at=captured,
            is_current=True,
        )
        evidence = Evidence(
            id=eid,
            source_document_id=sid,
            source_document=document,
            snapshot_record_id=sid,
            parser_rule=rule,
            evidence_type="html_section",
            locator=locator,
            excerpt=excerpt,
            content_hash=_digest(excerpt.encode()),
            review_status="machine_extracted",
        )
        objects[SnapshotRecord, sid] = snapshot
        objects[Evidence, eid] = evidence
        return evidence, snapshot, path

    tax_html = (
        "<table><tr><th>Synthetic</th>"
        "<th>\u963f\u91cc\u4e91\u4e2d\u56fd\u7ad9 (www.aliyun.com)</th><th>Intl</th></tr>"
        "<tr><td>\u4ea4\u6613\u8d27\u5e01</td><td>CNY</td><td>USD</td></tr>"
        "<tr><td>\u4ef7\u683c\u8bf4\u660e</td>"
        "<td>\u4ef7\u683c\u5305\u542b\u589e\u503c\u7a0e\u3002</td><td>Excluded</td></tr></table>"
    )
    clause = supporting_policies.extract_clauses(aliyun_promotion.TAX_SOURCE, tax_html)[0]
    tax, tax_snapshot, tax_path = source(
        aliyun_promotion.TAX_SOURCE,
        2,
        20,
        tax_html.encode(),
        json.dumps(clause, ensure_ascii=False, sort_keys=True),
        supporting_policies.RULE,
        f"policy:{aliyun_promotion.TAX_SOURCE}:clause[0]",
        now - timedelta(minutes=1),
    )
    catalog = make_catalog()
    headers = [
        "\u5b9e\u4f8b\u89c4\u683c",
        "vCPUs",
        "\u5185\u5b58(GiB)",
        "\u6309\u91cf\u76ee\u5f55\u4ef7",
        "\u5305\u6708\u76ee\u5f55\u4ef7",
        "\u5305\u5468\u4ef7\u683c",
        "\u6309\u91cf\u6708\u4ef7(30\u5929)",
    ]
    cells = [
        "\u901a\u7528\u578b ecs.g6.xlarge",
        "4",
        "16",
        "\uffe52.5",
        "\uffe5999",
        "\uffe5333",
        "\uffe51800",
    ]
    catalog["sections"][0]["tables"] = [
        "<table><thead><tr>"
        + "".join(f"<th>{x}</th>" for x in headers)
        + "</tr></thead><tbody><tr>"
        + "".join(f"<td>{x}</td>" for x in cells)
        + "</tr></tbody></table>"
    ]
    raw = json.dumps(catalog).encode()
    captured, records = inspect_catalog(raw)
    origin, catalog_snapshot, catalog_path = source(
        aliyun_promotion.SOURCE_ID,
        1,
        10,
        raw,
        json.dumps(records[0], ensure_ascii=False, sort_keys=True),
        CAPTURE_RULE,
        "browser:compute:table[0]:row[0]",
        captured,
    )
    expected = aliyun_promotion.extract_catalog_record(session, origin.id, tax.id)
    derived = Evidence(
        id=30,
        source_document_id=1,
        source_document=origin.source_document,
        snapshot_record_id=1,
        parser_rule=aliyun_promotion.RULE,
        evidence_type=expected.evidence_type,
        locator=expected.evidence_locator,
        excerpt=expected.evidence_excerpt,
        content_hash=_digest(expected.evidence_excerpt.encode()),
        review_status="machine_extracted",
    )
    objects[Evidence, 30] = derived
    return SimpleNamespace(**locals())


def _item(data, eid=30):
    return panel._evidence_packet(data.session, eid, data.tmp_path, data.now)[0]


def test_exact_reviewed_tax_document_admitted_without_domain_widening(public_scope):
    data = public_scope
    before = data.tax.excerpt
    item = _item(data, 20)
    assert item["source_url"] == panel.ALIYUN_TAX_URL
    assert item["excerpt"] == before
    assert item["policy_verification"]["scope"] == "china_site_tax_inclusion_only"
    assert not item["policy_verification"]["customer_eligible"]
    assert "alibabacloud.com" not in panel.OFFICIAL_HOSTS
    data.session.flush.assert_not_called()
    data.session.commit.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        panel.ALIYUN_TAX_URL + "/",
        panel.ALIYUN_TAX_URL + "?account_id=synthetic",
        panel.ALIYUN_TAX_URL + "#other",
        panel.ALIYUN_TAX_URL.replace("/zh/", "/en/"),
        panel.ALIYUN_TAX_URL.replace("www.", ""),
        panel.ALIYUN_TAX_URL.replace("www.", "help."),
        panel.ALIYUN_TAX_URL.replace(".com/", ".com.evil.invalid/"),
        panel.ALIYUN_TAX_URL.replace("https:", "http:"),
        "https://www.alibabacloud.com/help/zh/other",
    ],
)
def test_tax_near_miss_urls_rejected(public_scope, url):
    public_scope.tax.source_document.url = url
    with pytest.raises(ValueError, match="aliyun_tax_source_scope_invalid"):
        _item(public_scope, 20)


@pytest.mark.parametrize(
    "updates",
    [
        {"terms_review_status": "disallowed"},
        {"terms_review_status": "unknown"},
        {"review_status": "rejected"},
        {"reviewed_at": None},
        {"enabled": False},
        {"requires_authentication": True},
        {"requires_browser": True},
        {"automated_fetch_allowed": False},
        {"allow_automated_fetch": False},
        {"manual_only": True},
        {"provider_code": "other"},
        {"product_code": "oss"},
        {"cloud_partition": "aliyun_intl"},
        {"market_mode": "international"},
        {"source_type": "pricing"},
        {"authority_level": "unofficial"},
        {"source_id": "other_policy"},
        {"url": panel.ALIYUN_TAX_URL + "?other=1"},
    ],
)
def test_tax_registry_review_and_scope_required(public_scope, updates):
    data = public_scope
    key = aliyun_promotion.TAX_SOURCE
    data.entries[key] = data.entries[key].model_copy(update=updates)
    with pytest.raises(ValueError, match="aliyun_tax_source_scope_invalid"):
        _item(data, 20)


@pytest.mark.parametrize(
    "updates",
    [
        {"allowed_domains": ["alibabacloud.com"]},
        {"allowed_domains": ["www.alibabacloud.com", "other.invalid"]},
        {"allow_subdomains": True},
        {"allow_redirects": True},
    ],
)
def test_tax_domain_policy_must_remain_exact(public_scope, updates):
    data = public_scope
    key = aliyun_promotion.TAX_SOURCE
    entry = data.entries[key]
    data.entries[key] = entry.model_copy(
        update={"domain_policy": entry.domain_policy.model_copy(update=updates)}
    )
    with pytest.raises(ValueError, match="aliyun_tax_source_scope_invalid"):
        _item(data, 20)


@pytest.mark.parametrize(
    "change",
    [
        "raw",
        "excerpt",
        "hash",
        "locator",
        "parser",
        "rejected",
        "source_id",
        "document_id",
        "snapshot_id",
        "snapshot_old",
        "document_old",
        "partition",
        "provider",
        "future",
        "stale",
    ],
)
def test_tax_provenance_and_actual_dom_clause_required(public_scope, change):
    data = public_scope
    if change == "raw":
        data.tax_path.write_bytes(b"SYNTHETIC tampered raw")
    elif change == "excerpt":
        data.tax.excerpt = json.dumps({"headers": ["Synthetic"], "rows": [["Tax", "unknown"]]})
        data.tax.content_hash = _digest(data.tax.excerpt.encode())
    elif change == "hash":
        data.tax.content_hash = "a" * 64
    elif change == "locator":
        data.tax.locator += "other"
    elif change == "parser":
        data.tax.parser_rule = "unregistered"
    elif change == "rejected":
        data.tax.review_status = "rejected"
    elif change == "source_id":
        data.tax_snapshot.source_id = "unregistered"
    elif change == "document_id":
        data.tax.source_document_id = 999
    elif change == "snapshot_id":
        data.tax.snapshot_record_id = 999
    elif change == "snapshot_old":
        data.tax_snapshot.is_current = False
    elif change == "document_old":
        data.tax.source_document.is_current = False
    elif change == "partition":
        data.tax.source_document.cloud_partition = "aliyun_intl"
    elif change == "provider":
        data.provider.code = "other"
    elif change == "future":
        data.tax_snapshot.captured_at = data.now + timedelta(days=1)
    else:
        data.tax.source_document.captured_at = data.now - timedelta(days=500)
    with pytest.raises(ValueError):
        _item(data, 20)


def test_reconstructed_catalog_typed_exclusions_preserved_everywhere(public_scope):
    data = public_scope
    item = _item(data)
    trusted = frozenset({item["catalog_disclosure_verification"]["payload_sha256"]})
    derived = json.loads(data.derived.excerpt)
    payload = {
        "evidence": [item],
        "assumptions": {"input_scope": {"derived": derived}},
        "costs": [{"expected_price_scope": {"derived": deepcopy(derived)}}],
    }
    before = json.dumps(payload, ensure_ascii=False, default=str)
    panel._public(payload, verified_catalogs=trusted)
    assert json.dumps(payload, ensure_ascii=False, default=str) == before
    assert derived["excluded"] == [
        "live_purchase_quote",
        "availability",
        "personal_discounts",
        "vendor_equivalence",
    ]
    assert item["excerpt"] == data.derived.excerpt
    with pytest.raises(ValueError, match="sensitive_content_rejected"):
        panel._public(payload)
    graph, _ = panel._evidence_graph(
        data.session,
        {30},
        data.tmp_path,
        data.now,
        evidence_cutoff=data.now,
        market_mode="domestic",
    )
    assert set(graph) == {10, 20, 30}
    data.session.flush.assert_not_called()
    data.session.commit.assert_not_called()


@pytest.mark.parametrize(
    "excluded",
    [
        ["personal_discounts"],
        ["personal_discounts", "unknown"],
        [
            "live_purchase_quote",
            "availability",
            "personal_discounts",
            "vendor_equivalence",
            "unknown",
        ],
        ["live_purchase_quote", "availability", "personal_discounts=0", "vendor_equivalence"],
        ["live_purchase_quote", "availability", "PERSONAL_DISCOUNTS", "vendor_equivalence"],
        [
            "live_purchase_quote",
            "availability",
            {"personal_discounts": "synthetic"},
            "vendor_equivalence",
        ],
        "personal_discounts",
        {"personal_discounts": False},
        None,
    ],
)
def test_unknown_or_untyped_exclusions_never_authorized(public_scope, excluded):
    data = public_scope
    payload = json.loads(data.derived.excerpt)
    payload["excluded"] = excluded
    data.derived.excerpt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    data.derived.content_hash = _digest(data.derived.excerpt.encode())
    with pytest.raises(ValueError, match="catalog_disclosure_reconstruction_mismatch"):
        _item(data)


@pytest.mark.parametrize(
    "unsafe",
    [
        "personal_discounts",
        "No personal_discounts are used.",
        {"excluded": ["personal_discounts"]},
        {"personal_discounts": False},
        {"other": "personal_discounts"},
        {"account_id": "synthetic"},
        {"customer_id": "synthetic"},
        {"nested": {"customer_email": "synthetic@example.invalid"}},
        {"api_key": "synthetic"},
        {"token": "synthetic"},
        {"password": "synthetic"},
        '{"customer_id":"synthetic"}',
        '{"\\u0061ccount_id":"synthetic"}',
        '{"excluded":["personal_discounts"],"excluded":[]}',
    ],
)
def test_verified_exclusions_do_not_authorize_other_fields_or_free_text(public_scope, unsafe):
    item = _item(public_scope)
    trusted = frozenset({item["catalog_disclosure_verification"]["payload_sha256"]})
    with pytest.raises(ValueError, match="sensitive_content_rejected"):
        panel._public({"valid": item, "unsafe": unsafe}, verified_catalogs=trusted)


@pytest.mark.parametrize(
    "change", ["registry", "tax_registry", "raw", "origin", "rejected", "rule", "locator", "type"]
)
def test_exclusion_authority_requires_current_reviewed_reconstructed_evidence(public_scope, change):
    data = public_scope
    if change in {"registry", "tax_registry"}:
        key = aliyun_promotion.SOURCE_ID if change == "registry" else aliyun_promotion.TAX_SOURCE
        data.entries[key] = data.entries[key].model_copy(
            update={"terms_review_status": "disallowed"}
        )
    elif change == "raw":
        data.catalog_path.write_bytes(b"SYNTHETIC tampered")
    elif change == "origin":
        data.origin.excerpt = "{}"
        data.origin.content_hash = _digest(b"{}")
    elif change == "rejected":
        data.derived.review_status = "rejected"
    elif change == "locator":
        data.derived.locator += "other"
    elif change == "type":
        data.derived.evidence_type = "html_section"
    else:
        data.derived.parser_rule = "unregistered"
    with pytest.raises(ValueError):
        _item(data)


def test_tax_admission_never_extends_to_other_sources_or_markets(public_scope):
    data = public_scope
    with pytest.raises(ValueError, match="policy_scenario_market_mismatch"):
        panel._evidence_graph(
            data.session,
            {20},
            data.tmp_path,
            data.now,
            evidence_cutoff=data.now,
            market_mode="international",
        )
    data.tax_snapshot.source_id = "other_source"
    data.tax.source_document.url = "https://www.alibabacloud.com/help/zh/other"
    with pytest.raises(ValueError, match="evidence_not_public_official"):
        _item(data, 20)


def test_registry_state_is_bound_to_the_public_evidence_proof(public_scope):
    data = public_scope
    first = _item(data)
    key = aliyun_promotion.TAX_SOURCE
    data.entries[key] = data.entries[key].model_copy(
        update={"compliance_notes": "Synthetic reviewed policy metadata changed."}
    )
    second = _item(data)
    assert first["excerpt"] == second["excerpt"]
    assert panel._hash(first) != panel._hash(second)
    data.entries[key] = data.entries[key].model_copy(
        update={"reviewed_at": data.now + timedelta(days=1)}
    )
    with pytest.raises(ValueError, match="aliyun_tax_source_scope_invalid"):
        _item(data)
