from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import func, select

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing import extraction, supporting_policies
from cloud_expert.pricing.supporting_policies import extract_clauses
from tests.fixtures.synthetic_data import load_synthetic_fixture

FIXED_IPV4_HTML = (
    "<p>Synthetic: 配置固定公网IP后，阿里云仅对出方向流量计费，入方向不计费。</p>"
    "<p>本文仅介绍固定公网IPv4的两种计费模式。EIP and NAT excluded.</p>"
    "<p>按使用流量计费均按照实例实际使用的出网流量后付费。</p>"
)


def test_china_tax_clause_does_not_take_international_column():
    html = (
        "<table><tr><th>差异点</th><th>阿里云中国站 (www.aliyun.com)</th><th>International</th></tr>"
        "<tr><td>交易货币</td><td>CNY</td><td>USD</td></tr>"
        "<tr><td>价格说明</td><td>价格包含增值税。</td><td>Not included</td></tr></table>"
    )
    result = extract_clauses("aliyun_china_billing_tax_policy", html)
    assert result[0]["rows"] == [["交易货币", "CNY"], ["价格说明", "价格包含增值税。"]]
    assert "USD" not in str(result)
    with pytest.raises(ValueError):
        extract_clauses(
            "aliyun_china_billing_tax_policy", html.replace("www.aliyun.com", "example.com")
        )


def test_basic_support_requires_header_and_domestic_currency_context():
    html = (
        "<table><tr><th>Support Plan</th><th>Basic</th><th>Paid</th></tr>"
        "<tr><td>Billing standard</td><td>Free</td><td>CNY 987</td></tr></table>"
    )
    assert extract_clauses("aliyun_basic_support_policy", html)[0]["rows"] == [
        ["Billing standard", "Free"]
    ]
    with pytest.raises(ValueError):
        extract_clauses("aliyun_basic_support_policy", html.replace("CNY", "USD"))


@pytest.mark.parametrize(
    "source,clause",
    [
        ("huawei_cloud_basic_support_policy", "华为云支持计划基础级支持免费提供"),
        ("huawei_cloud_eip_binding_policy", "已绑定实例的按需计费的EIP不收取弹性公网IP保有费"),
    ],
)
def test_clauses_retain_qualifying_context(source, clause):
    text = f"Synthetic fixture: {clause}; scope remains limited."
    assert extract_clauses(source, f"<p>{text}</p>") == [{"clause": text}]
    with pytest.raises(ValueError):
        extract_clauses(source, "<p>No matching rule</p>")


def test_both_size_units_are_required():
    assert (
        len(
            extract_clauses(
                "huawei_cloud_pricing_api_parameters", "<li>15：Mbps</li><li>17：GB</li>"
            )
        )
        == 2
    )
    with pytest.raises(ValueError):
        extract_clauses("huawei_cloud_pricing_api_parameters", "<li>17：GB</li>")
    with pytest.raises(ValueError):
        extract_clauses("not_registered", "<p>anything</p>")


def test_fixed_ipv4_policy_preserves_ip_type_and_never_example_prices():
    clause = extract_clauses("aliyun_ecs_fixed_ipv4_billing_policy", FIXED_IPV4_HTML)[0]
    assert clause["ip_type"] == "instance_assigned_fixed_ipv4"
    assert "eip" in clause["excludes"] and "example_prices" in clause["excludes"]
    with pytest.raises(ValueError):
        extract_clauses("aliyun_ecs_fixed_ipv4_billing_policy", "<p>Free IP</p>")


def test_policy_persistence_rechecks_provenance_and_is_idempotent(session, tmp_path, monkeypatch):
    fixture = load_synthetic_fixture(session)
    provider = fixture["product"].provider
    htmls = [
        "<p>Synthetic: 华为云支持计划基础级支持免费提供</p>",
        "<p>Synthetic: 已绑定实例的按需计费的EIP不收取弹性公网IP保有费</p>",
        "<ul><li>15：Mbps</li><li>17：GB</li></ul>",
        "<table><tr><th>差异点</th><th>阿里云中国站 (www.aliyun.com)</th><th>Intl</th></tr>"
        "<tr><td>交易货币</td><td>CNY</td><td>USD</td></tr>"
        "<tr><td>价格说明</td><td>价格包含增值税。</td><td>No</td></tr></table>",
        "<table><tr><th>Support Plan</th><th>Basic</th><th>Paid</th></tr>"
        "<tr><td>Billing standard</td><td>Free</td><td>CNY 987</td></tr></table>",
        FIXED_IPV4_HTML,
    ]
    entries = {}
    for code, html in zip(supporting_policies.POLICY_SOURCES, htmls, strict=True):
        entry = get_entry_by_source_id(code).model_copy(update={"provider_code": provider.code})
        entries[code] = entry
        raw = html.encode()
        path = f"{code}.html"
        (tmp_path / path).write_bytes(raw)
        document = SourceDocument(
            provider_id=provider.id,
            title="Synthetic policy",
            source_type="documentation",
            url=entry.url,
            cloud_partition=entry.cloud_partition,
            language="zh-CN",
            authority_level="official_primary",
            content_hash=sha256(raw).hexdigest(),
            captured_at=datetime.now(UTC),
            is_current=True,
        )
        session.add(document)
        session.flush()
        session.add(
            SnapshotRecord(
                source_document_id=document.id,
                source_id=code,
                content_hash=document.content_hash,
                storage_path=path,
                manifest_path="synthetic_manifest.json",
                content_type="text/html",
                content_length_bytes=len(raw),
                captured_at=datetime.now(UTC),
                change_status="first_seen",
                is_current=True,
            )
        )
    session.flush()
    monkeypatch.setattr(extraction, "_raw_data_dir", lambda: tmp_path)
    monkeypatch.setattr(supporting_policies, "get_entry_by_source_id", entries.get)
    first = supporting_policies.persist_policy_evidence(session)
    count = session.scalar(select(func.count()).select_from(Evidence))
    assert supporting_policies.persist_policy_evidence(session) == first
    assert session.scalar(select(func.count()).select_from(Evidence)) == count
    evidence = session.get(Evidence, first[0]["evidence_ids"][0])
    original = evidence.excerpt
    evidence.excerpt = "tampered"
    session.flush()
    with pytest.raises(ValueError, match="immutable"):
        supporting_policies.persist_policy_evidence(session)
    evidence.excerpt = original
    evidence.source_document.cloud_partition = "huawei_intl"
    session.flush()
    with pytest.raises(ValueError, match="provenance"):
        supporting_policies.persist_policy_evidence(session)
