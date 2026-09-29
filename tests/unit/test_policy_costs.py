"""Synthetic policy fixtures; none of these records approve real cloud facts."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry import loader as registry_loader
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import policy_costs
from cloud_expert.pricing.policy_costs import PolicyContext, validate_zero_cost_policy
from cloud_expert.pricing.supporting_policies import RULE, extract_clauses
from tests.fixtures.synthetic_data import load_synthetic_fixture
from tests.unit.test_supporting_price_policies import FIXED_IPV4_HTML


@pytest.fixture(scope="session")
def policy_registry_entries():
    return registry_loader.load_registry_entries()


@pytest.fixture(autouse=True)
def isolated_policy_registry(monkeypatch, policy_registry_entries):
    # Reuse parsed registry files, but clone entries so mutations never leak
    # between synthetic cases. Production validation itself is not mocked.
    original = registry_loader.load_registry_entries
    monkeypatch.setattr(
        registry_loader,
        "load_registry_entries",
        lambda registry_dir=None: (
            [entry.model_copy(deep=True) for entry in policy_registry_entries]
            if registry_dir is None
            else original(registry_dir)
        ),
    )


def make_policy(session, store, provider_id, source_id):
    htmls = {
        "aliyun_ecs_fixed_ipv4_billing_policy": FIXED_IPV4_HTML,
        "huawei_cloud_basic_support_policy": "<p>Synthetic: \u534e\u4e3a\u4e91\u652f\u6301\u8ba1\u5212\u57fa\u7840\u7ea7\u652f\u6301\u514d\u8d39\u63d0\u4f9b</p>",
        "huawei_cloud_eip_binding_policy": "<p>Synthetic: \u5df2\u7ed1\u5b9a\u5b9e\u4f8b\u7684\u6309\u9700\u8ba1\u8d39\u7684EIP\u4e0d\u6536\u53d6\u5f39\u6027\u516c\u7f51IP\u4fdd\u6709\u8d39</p>",
        "aliyun_basic_support_policy": "<p>Synthetic</p><table><tr><th>Support Plan</th><th>Basic</th><th>Paid</th></tr><tr><td>Billing standard</td><td>Free</td><td>CNY 123</td></tr></table>",
    }
    raw = htmls[source_id].encode()
    entry = get_entry_by_source_id(source_id)
    at = datetime.now(UTC) - timedelta(hours=1)
    stored = store.store(
        entry=entry,
        requested_url=entry.url,
        final_url=entry.url,
        http_status=200,
        content_type="text/html",
        content=raw,
        response_headers={},
        content_metadata={"synthetic": True},
        fetch_duration_ms=0,
        captured_at=at,
    )
    document = SourceDocument(
        provider_id=provider_id,
        title="Synthetic zero fee policy fixture",
        source_type="documentation",
        url=entry.url,
        cloud_partition=entry.cloud_partition,
        authority_level="official_primary",
        content_hash=sha256(raw).hexdigest(),
        captured_at=at,
        is_current=True,
    )
    session.add(document)
    session.flush()
    snapshot = SnapshotRecord(
        source_document_id=document.id,
        source_id=source_id,
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
    excerpt = json.dumps(extract_clauses(source_id, raw.decode())[0], sort_keys=True)
    evidence = Evidence(
        source_document_id=document.id,
        snapshot_record_id=snapshot.id,
        locator="synthetic:policy",
        excerpt=excerpt,
        content_hash=sha256(excerpt.encode()).hexdigest(),
        evidence_type="html_section",
        parser_rule=RULE,
        confidence=1.0,
        review_status="machine_extracted",
    )
    session.add(evidence)
    session.flush()
    return evidence, snapshot


@pytest.fixture
def policy_input(session, tmp_path):
    fixture = load_synthetic_fixture(session)
    product, region = fixture["product"], fixture["region"]
    product.provider.code, product.code = "huawei_cloud", "ecs"
    partition = CloudPartition(
        provider_id=product.provider_id,
        partition_code="huawei_cn",
        partition_name="Synthetic",
        market_mode="domestic",
    )
    session.add(partition)
    session.flush()
    region.code, region.cloud_partition_id = "cn-north-4", partition.id
    store = SnapshotStore(tmp_path / "raw")
    evidence, snapshot = make_policy(
        session, store, product.provider_id, "huawei_cloud_eip_binding_policy"
    )
    context = PolicyContext(
        provider_id=product.provider_id,
        product_id=product.id,
        provider_code="huawei_cloud",
        partition="huawei_cn",
        region=region.code,
        duration_hours="730",
        support_plan="basic",
        eip_binding="bound",
        eip_bound_hours="730",
    )
    session.flush()
    return context, evidence, snapshot, store


def test_policy_receipt_is_not_price_or_approval(session, policy_input):
    context, evidence, snapshot, store = policy_input
    receipt = validate_zero_cost_policy(
        session,
        policy_code="huawei_bound_eip",
        evidence_id=evidence.id,
        context=context,
        root=store.raw_data_dir,
    )
    assert receipt["amount"] == "0"
    assert receipt["only_dimension"] == "ip_holding"
    assert receipt["raw_sha256"] == snapshot.content_hash
    assert not receipt["price_snapshot_created"]
    assert not receipt["model_approved"] and not receipt["customer_eligible"]
    assert evidence.source_document.source_type == "documentation"
    assert not session.new and not session.dirty


@pytest.mark.parametrize(
    "mutation",
    [
        "raw",
        "manifest",
        "hash",
        "rejected",
        "source",
        "document_hash",
        "not_current",
        "old",
        "future",
        "path",
        "source_type",
        "region",
        "terms",
        "clause",
        "parser",
    ],
)
def test_policy_fail_closed_on_changed_evidence(session, policy_input, monkeypatch, mutation):
    context, evidence, snapshot, store = policy_input
    if mutation == "raw":
        (store.raw_data_dir / snapshot.storage_path).write_bytes(b"tampered")
    elif mutation == "manifest":
        path = store.raw_data_dir / snapshot.manifest_path
        data = json.loads(path.read_text())
        data["source_id"] = "synthetic_wrong_source"
        path.write_text(json.dumps(data))
    elif mutation == "hash":
        evidence.content_hash = "0" * 64
    elif mutation == "rejected":
        evidence.review_status = "rejected"
    elif mutation == "source":
        evidence.source_document.cloud_partition = "huawei_intl"
    elif mutation == "document_hash":
        evidence.source_document.content_hash = "0" * 64
    elif mutation == "not_current":
        snapshot.is_current = False
    elif mutation == "old":
        snapshot.captured_at -= timedelta(days=31)
    elif mutation == "future":
        snapshot.captured_at += timedelta(days=1)
    elif mutation == "path":
        snapshot.storage_path = "../escape.html"
    elif mutation == "source_type":
        evidence.source_document.source_type = "pricing"
    elif mutation == "region":
        context = context.model_copy(update={"region": "not-a-region"})
    elif mutation == "terms":
        entry = get_entry_by_source_id(snapshot.source_id).model_copy(
            update={"terms_review_status": "disallowed"}
        )
        monkeypatch.setattr(policy_costs, "get_entry_by_source_id", lambda _: entry)
    elif mutation == "parser":
        evidence.parser_rule = "unknown_parser"
    else:
        evidence.excerpt = '{"clause": "fabricated free fee"}'
        evidence.content_hash = sha256(evidence.excerpt.encode()).hexdigest()
    with pytest.raises(ValueError):
        validate_zero_cost_policy(
            session,
            policy_code="huawei_bound_eip",
            evidence_id=evidence.id,
            context=context,
            root=store.raw_data_dir,
        )


@pytest.mark.parametrize(
    "binding,hours", [("bound", "729"), ("unbound", "0"), ("unknown", "0"), ("not_deployed", "0")]
)
def test_no_free_holding_fee_for_partial_or_unknown_binding(session, policy_input, binding, hours):
    context, evidence, _, store = policy_input
    context = context.model_copy(update={"eip_binding": binding, "eip_bound_hours": Decimal(hours)})
    with pytest.raises(ValueError, match="entire"):
        validate_zero_cost_policy(
            session,
            policy_code="huawei_bound_eip",
            evidence_id=evidence.id,
            context=context,
            root=store.raw_data_dir,
        )


def test_support_plan_and_provider_are_explicit(session, policy_input):
    context, _, _, store = policy_input
    support, _ = make_policy(
        session, store, context.provider_id, "huawei_cloud_basic_support_policy"
    )
    assert (
        validate_zero_cost_policy(
            session,
            policy_code="huawei_basic_support",
            evidence_id=support.id,
            context=context,
            root=store.raw_data_dir,
        )["only_dimension"]
        == "support"
    )
    with pytest.raises(ValueError, match="basic plan"):
        validate_zero_cost_policy(
            session,
            policy_code="huawei_basic_support",
            evidence_id=support.id,
            context=context.model_copy(update={"support_plan": "paid"}),
            root=store.raw_data_dir,
        )
    with pytest.raises(ValueError, match="partition"):
        validate_zero_cost_policy(
            session,
            policy_code="aliyun_basic_support",
            evidence_id=support.id,
            context=context,
            root=store.raw_data_dir,
        )
    with pytest.raises(ValueError, match="unsupported"):
        validate_zero_cost_policy(
            session,
            policy_code="all_network_free",
            evidence_id=support.id,
            context=context,
            root=store.raw_data_dir,
        )
