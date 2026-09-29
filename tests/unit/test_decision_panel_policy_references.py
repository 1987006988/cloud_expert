"""Synthetic-only policy graph fixtures. No real models, network or business database."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.model_review import decision_panel as panel
from cloud_expert.pricing import aws_billing_policy as billing
from cloud_expert.pricing import aws_document_policy as documents
from tests.unit.test_aws_billing_policy import HTML, policy_entry, provider, store_snapshot
from tests.unit.test_aws_document_policy import LIFECYCLE, METRICS, PRINCIPLES, SOURCES, USAGE, html
from tests.unit.test_decision_panel import graph  # noqa: F401
from tests.unit.test_official_catalog import NOW, fixture


def doc_entry(source_id):
    product, url, _, _ = SOURCES[source_id]
    return SourceRegistryEntry.model_validate(
        {
            "source_id": source_id,
            "provider_code": "aws",
            "market_mode": "international",
            "cloud_partition": "aws",
            "product_code": product,
            "source_type": "documentation",
            "title": "SYNTHETIC DOCUMENT",
            "authority_level": "official_primary",
            "url": url,
            "expected_content_type": ["text/html"],
            "expected_encoding": "utf-8",
            "domain_policy": {"allowed_domains": ["docs.aws.amazon.com"], "allow_redirects": False},
            "reviewed_at": NOW - timedelta(days=2),
            "robots_checked_at": NOW - timedelta(days=2),
            "robots_allowed": True,
            "terms_review_status": "approved",
            "automated_fetch_allowed": True,
            "compliance_notes": "SYNTHETIC docs.aws.amazon.com CC-BY-SA-4.0 approval only.",
            "notes": "SYNTHETIC fixture only; no actual facts approved.",
        }
    )


def reference(record):
    return {
        key: record[key]
        for key in (
            "kind",
            "snapshot_record_id",
            "source_document_id",
            "raw_sha256",
            "locator",
            "content_hash",
            "parser_rule",
        )
    }


def set_payload(row, payload):
    row.excerpt = billing.canonical(payload)
    row.content_hash = billing.digest(row.excerpt)


@pytest.fixture
def policy_graph(session, tmp_path, monkeypatch):
    owner = provider(session)
    catalog_entry, catalog, _ = fixture()
    entries = {catalog_entry.source_id: catalog_entry}
    catalog_snapshot = store_snapshot(
        session, tmp_path, catalog_entry, json.dumps(catalog).encode(), owner
    )
    monkeypatch.setattr(documents, "get_entry_by_source_id", entries.get)
    monkeypatch.setattr(billing, "get_entry_by_source_id", entries.get)
    monkeypatch.setattr(panel, "get_entry_by_source_id", entries.get)
    docs = {}

    def add_doc(source_id):
        entry = doc_entry(source_id)
        entries[source_id] = entry
        snapshot = store_snapshot(session, tmp_path, entry, html(source_id).encode(), owner)
        # The reused synthetic snapshot fixture normally builds pricing documents.
        snapshot.source_document.source_type = "documentation"
        session.commit()
        plan = documents.prepare_document_policy(session, snapshot.id, raw_root=tmp_path, as_of=NOW)
        evidence = [billing.evidence_row(session, record, apply=True) for record in plan["records"]]
        session.commit()
        docs[source_id] = SimpleNamespace(
            snapshot=snapshot, entry=entry, plan=plan, evidence=evidence
        )
        return docs[source_id]

    tax = add_doc(PRINCIPLES)

    def generic(payload):
        row = Evidence(
            source_document_id=catalog_snapshot.source_document_id,
            snapshot_record_id=catalog_snapshot.id,
            locator="json:synthetic",
            parser_rule="synthetic_graph_fixture",
            evidence_type="json_path",
            confidence=1,
            review_status="machine_extracted",
        )
        set_payload(row, payload)
        session.add(row)
        session.commit()
        return row

    root = generic(
        {"synthetic": True, "policy_evidence_references": [reference(tax.plan["records"][0])]}
    )

    def collect(*, roots=None, market="international", cutoff=NOW):
        session.expire_all()
        return panel._evidence_graph(
            session, roots or {root.id}, tmp_path, NOW, evidence_cutoff=cutoff, market_mode=market
        )

    return SimpleNamespace(
        root=root,
        docs=docs,
        entries=entries,
        catalog=catalog_snapshot,
        tax=tax,
        add_doc=add_doc,
        generic=generic,
        collect=collect,
        path=tmp_path,
    )


def test_legacy_reference_resolves_real_doc_rows_and_scoped_license(session, policy_graph):
    g = policy_graph
    session.rollback()
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(session.get_bind(), "before_cursor_execute", capture)
    try:
        items, rows = g.collect()
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", capture)
    target = g.tax.evidence[0]
    assert set(items) == {g.root.id, target.id}
    assert target in rows and target.source_document in rows and g.tax.snapshot in rows
    proof = items[target.id]["policy_verification"]
    assert proof["license"]["identifier"] == "CC-BY-SA-4.0"
    assert proof["binding"]["registry_sha256"] == g.tax.plan["binding"]["registry_sha256"]
    assert proof["binding"]["manifest_sha256"] == g.tax.plan["binding"]["manifest_sha256"]
    assert proof["scope"] == "general_aws_pricing_principles_only"
    assert proof["review_required"] and not proof["billing_conversion_authorized"]
    assert (
        not proof["price_approval"] and not proof["customer_eligible"] and not proof["tco_eligible"]
    )
    assert items[g.root.id]["policy_evidence_references"][0]["evidence_id"] == target.id
    assert statements and set(statements) <= {"SELECT"}
    assert not session.new and not session.dirty and not session.deleted


@pytest.mark.parametrize("source_id", [PRINCIPLES, METRICS, USAGE, LIFECYCLE])
def test_all_document_record_forms_are_reconstructed_without_scope_promotion(
    session, policy_graph, source_id
):
    g = policy_graph
    doc = g.docs.get(source_id) or g.add_doc(source_id)
    # Direct document roots need no synthetic product-specific parent.
    items, _ = g.collect(roots={row.id for row in doc.evidence})
    for row in doc.evidence:
        assert items[row.id]["policy_verification"]["scope"] == documents.DOCUMENTS[source_id].scope
        assert items[row.id]["policy_verification"]["billing_conversion_authorized"] is False


def test_nested_lists_and_transitive_supporting_refs_include_all_sources(session, policy_graph):
    g = policy_graph
    usage = g.add_doc(USAGE)
    middle = g.generic(
        {
            "nested": [
                {"deeper": {"policy_evidence_references": [reference(usage.plan["records"][1])]}}
            ]
        }
    )
    payload = json.loads(g.root.excerpt)
    payload["nested"] = [{"supporting_hashes": {str(middle.id): middle.content_hash}}]
    set_payload(g.root, payload)
    session.commit()
    items, rows = g.collect()
    assert set(items) == {g.root.id, middle.id, g.tax.evidence[0].id, usage.evidence[1].id}
    assert usage.snapshot in rows and usage.snapshot.source_document in rows
    assert items[usage.evidence[1].id]["policy_verification"]["kind"] == "request_tier1_usage_code"
    assert items[middle.id]["policy_evidence_references"][0]["evidence_id"] == usage.evidence[1].id


def test_id_hash_scope_form_and_shared_dag_are_supported(session, policy_graph):
    g = policy_graph
    target = g.tax.evidence[0]
    bound = {
        "evidence_id": target.id,
        "content_hash": target.content_hash,
        "scope": g.tax.plan["records"][0]["scope"],
    }
    middle = g.generic({"policy_evidence_references": [bound]})
    set_payload(g.root, {"source_evidence_id": middle.id, "policy_evidence_references": [bound]})
    session.commit()
    items, _ = g.collect()
    assert set(items) == {g.root.id, middle.id, target.id}


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "hash",
        "snapshot",
        "document",
        "raw_hash",
        "kind",
        "scope",
        "id_bool",
        "unknown_key",
        "null_list",
        "empty_list",
        "missing_binding",
        "nested_missing",
        "parser",
    ],
)
def test_reference_binding_fails_closed(session, policy_graph, mutation):
    g = policy_graph
    payload = json.loads(g.root.excerpt)
    ref = payload["policy_evidence_references"][0]
    target = g.tax.evidence[0]
    if mutation == "missing":
        session.delete(target)
    elif mutation == "duplicate":
        session.add(
            Evidence(
                **{
                    key: getattr(target, key)
                    for key in (
                        "source_document_id",
                        "snapshot_record_id",
                        "locator",
                        "excerpt",
                        "content_hash",
                        "parser_rule",
                        "evidence_type",
                        "confidence",
                        "review_status",
                    )
                }
            )
        )
    elif mutation == "hash":
        ref["content_hash"] = "0" * 64
    elif mutation == "snapshot":
        ref["snapshot_record_id"] = 999999
    elif mutation == "document":
        ref["source_document_id"] += 100
    elif mutation == "raw_hash":
        ref["raw_sha256"] = "0" * 64
    elif mutation == "kind":
        ref["kind"] = "complete_price_approval"
    elif mutation == "scope":
        ref["scope"] = "all_storage_billing"
    elif mutation == "id_bool":
        ref["evidence_id"] = True
    elif mutation == "unknown_key":
        ref["override_approval"] = True
    elif mutation in {"null_list", "empty_list"}:
        payload["policy_evidence_references"] = None if mutation == "null_list" else []
    elif mutation == "missing_binding":
        payload["policy_evidence_references"] = [{"content_hash": target.content_hash}]
    elif mutation == "nested_missing":
        payload = {"nested": [{"policy_evidence_references": [{**ref, "evidence_id": 99999}]}]}
    else:
        ref["parser_rule"] = "unknown_policy_version"
    set_payload(g.root, payload)
    session.commit()
    with pytest.raises(ValueError):
        g.collect()


@pytest.mark.parametrize(
    "mutation",
    [
        "raw",
        "manifest",
        "license",
        "registry",
        "registry_missing",
        "excerpt",
        "parser",
        "rejected",
        "source_id",
        "document_binding",
    ],
)
def test_current_source_or_license_tamper_invalidates_nested_policy(
    session, policy_graph, mutation
):
    g = policy_graph
    doc = g.tax
    target = doc.evidence[0]
    if mutation == "raw":
        path = g.path / doc.snapshot.storage_path
        path.write_bytes(path.read_bytes() + b"tamper")
    elif mutation == "manifest":
        path = g.path / doc.snapshot.manifest_path
        manifest = json.loads(path.read_bytes())
        manifest["product_code"] = "ec2"
        path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "license":
        g.entries[PRINCIPLES] = doc.entry.model_copy(
            update={"compliance_notes": "No licensed approval"}
        )
    elif mutation == "registry":
        g.entries[PRINCIPLES] = doc.entry.model_copy(update={"notes": "changed registry binding"})
    elif mutation == "registry_missing":
        del g.entries[PRINCIPLES]
    elif mutation == "excerpt":
        payload = json.loads(target.excerpt)
        payload["price_approval"] = True
        set_payload(target, payload)
        root = json.loads(g.root.excerpt)
        root["policy_evidence_references"][0]["content_hash"] = target.content_hash
        set_payload(g.root, root)  # Even consistent forged hash links cannot waive re-extraction.
    elif mutation == "parser":
        target.parser_rule = "unknown_doc_parser"
    elif mutation == "rejected":
        target.review_status = "rejected"
    elif mutation == "source_id":
        doc.snapshot.source_id = "unregistered"
    else:
        target.source_document_id = g.catalog.source_document_id
    session.commit()
    with pytest.raises(ValueError):
        g.collect()


@pytest.mark.parametrize(
    "mutation",
    [
        "parent_partition",
        "parent_provider",
        "parent_registry_market",
        "document_partition",
        "scenario_market",
        "product",
    ],
)
def test_cross_market_or_product_reference_is_rejected(session, policy_graph, mutation):
    g = policy_graph
    if mutation == "parent_partition":
        g.root.source_document.cloud_partition = "aws_cn"
    elif mutation == "parent_provider":
        # Preserve foreign keys; the provider identity in the registry must still match.
        entry = g.entries[g.catalog.source_id]
        g.entries[g.catalog.source_id] = entry.model_copy(update={"provider_code": "huawei"})
    elif mutation == "parent_registry_market":
        entry = g.entries[g.catalog.source_id]
        g.entries[g.catalog.source_id] = entry.model_copy(update={"market_mode": "domestic"})
    elif mutation == "document_partition":
        g.tax.snapshot.source_document.cloud_partition = "aws_cn"
    elif mutation == "product":
        ec2 = g.add_doc(LIFECYCLE)
        set_payload(g.root, {"policy_evidence_references": [reference(ec2.plan["records"][0])]})
    session.commit()
    with pytest.raises(ValueError):
        g.collect(market="domestic" if mutation == "scenario_market" else "international")


@pytest.mark.parametrize("cycle", ["self", "two_nodes", "nested"])
def test_reference_cycles_are_rejected_not_silently_deduplicated(session, policy_graph, cycle):
    g = policy_graph
    if cycle == "self":
        set_payload(g.root, {"source_evidence_id": g.root.id})
    else:
        child = g.generic({"target_evidence_id": g.root.id})
        payload = {"source_evidence_id": child.id}
        set_payload(g.root, payload if cycle == "two_nodes" else {"nested": [payload]})
    session.commit()
    with pytest.raises(ValueError, match="evidence_reference_cycle"):
        g.collect()


def test_no_fallback_from_retired_website_to_new_document(session, policy_graph):
    g = policy_graph
    entry = policy_entry()
    g.entries[entry.source_id] = entry
    snapshot = store_snapshot(
        session, g.path, entry, HTML.encode(), g.root.source_document.provider
    )
    session.commit()
    legacy = billing.prepare_billing_policy(
        session, snapshot.id, product_code="s3", raw_root=g.path, as_of=NOW
    )
    old = billing.evidence_row(session, legacy["records"][0], apply=True)
    payload = json.loads(g.root.excerpt)
    payload["policy_evidence_references"].append(reference(legacy["records"][0]))
    set_payload(g.root, payload)
    session.commit()
    assert old.id in g.collect()[0]
    g.entries[entry.source_id] = entry.model_copy(
        update={"enabled": False, "automated_fetch_allowed": False}
    )
    with pytest.raises(ValueError, match="authorization"):
        g.collect()


def test_recursive_future_capture_missing_id_and_nesting_are_blocked(session, policy_graph):
    g = policy_graph
    with pytest.raises(ValueError, match="evidence_after_decision_cutoff"):
        g.collect(cutoff=NOW - timedelta(days=2))
    set_payload(g.root, {"nested": {"supporting_hashes": {"999999": "a" * 64}}})
    session.commit()
    with pytest.raises(ValueError, match="supporting_evidence_hash_mismatch"):
        g.collect()
    nested = {}
    for _ in range(34):
        nested = {"child": nested}
    set_payload(g.root, nested)
    session.commit()
    with pytest.raises(ValueError, match="evidence_reference_nesting_limit"):
        g.collect()


def test_referenced_policy_rows_and_license_are_fingerprint_inputs(session, policy_graph):
    g = policy_graph
    first, rows = g.collect()
    fingerprint = panel._hash(
        {"evidence": first, "records": [panel._row_digest(row) for row in rows]}
    )
    # A different valid declared parent registry scope note changes the packet proof.
    entry = g.entries[g.catalog.source_id]
    g.entries[g.catalog.source_id] = entry.model_copy(
        update={"notes": "new synthetic parent scope note"}
    )
    second, next_rows = g.collect()
    assert (
        panel._hash({"evidence": second, "records": [panel._row_digest(row) for row in next_rows]})
        != fingerprint
    )
    assert set(first) == set(second)
    assert first[g.tax.evidence[0].id]["policy_verification"]["license"]
    assert len(list(session.scalars(select(Evidence)))) == 3


@pytest.mark.parametrize("mutation", ["disabled", "terms", "missing", "host", "source_binding"])
def test_catalog_host_requires_current_exact_registry_proof(session, policy_graph, mutation):
    g = policy_graph
    source_id = g.catalog.source_id
    if mutation == "disabled":
        g.entries[source_id] = g.entries[source_id].model_copy(update={"enabled": False})
    elif mutation == "terms":
        g.entries[source_id] = g.entries[source_id].model_copy(
            update={"terms_review_status": "unknown"}
        )
    elif mutation == "missing":
        del g.entries[source_id]
    elif mutation == "host":
        g.catalog.source_document.url = (
            "https://pricing.us-east-1.amazonaws.com.evil.invalid/catalog"
        )
    else:
        payload = json.loads(g.root.excerpt)
        payload["registry_sha256"] = "0" * 64
        set_payload(g.root, payload)
    session.commit()
    with pytest.raises(ValueError):
        g.collect()


@pytest.mark.parametrize(
    "field,value", [("locator", []), ("parser_rule", {}), ("raw_sha256", None)]
)
def test_malformed_reference_rejected_before_database_binding(session, policy_graph, field, value):
    g = policy_graph
    payload = json.loads(g.root.excerpt)
    payload["policy_evidence_references"][0][field] = value
    set_payload(g.root, payload)
    session.commit()
    with pytest.raises(ValueError, match="policy_reference_type_invalid"):
        g.collect()


@pytest.mark.parametrize("form", ["caller_pin", "adapter_expanded"])
def test_document_catalog_typed_reference_contract_without_fixed_ids(session, policy_graph, form):
    g = policy_graph
    row, record = g.tax.evidence[0], g.tax.plan["records"][0]
    pinned = {"kind": record["kind"], "evidence_id": row.id, "content_hash": row.content_hash}
    if form == "adapter_expanded":
        pinned.update(
            {
                "reference_type": "aws_document_policy_evidence",
                "scope": record["scope"],
                "source_id": record["source_id"],
                **{
                    key: record[key]
                    for key in (
                        "source_document_id",
                        "snapshot_record_id",
                        "raw_sha256",
                        "source_url",
                        "manifest_sha256",
                        "registry_sha256",
                        "locator",
                        "parser_rule",
                    )
                },
            }
        )
    set_payload(g.root, {"policy_evidence_references": [pinned]})
    session.commit()
    items, _ = g.collect()
    assert items[row.id]["policy_verification"]["kind"] == record["kind"]
    assert items[g.root.id]["policy_evidence_references"][0]["reference"] == pinned
    pinned["reference_type"] = "website_license_override"
    set_payload(g.root, {"policy_evidence_references": [pinned]})
    session.commit()
    with pytest.raises(ValueError, match="policy_reference_type_mismatch"):
        g.collect()


@pytest.mark.parametrize("rule", ["aws_unknown", "aws_document_catalog_derivation_v2"])
def test_packet_checks_current_aws_consumer_even_after_tco_precheck(graph, monkeypatch, rule):  # noqa: F811
    # Isolate the panel's extra guard; a valid evidence graph cannot activate a price rule.
    graph.price.evidence.parser_rule = rule
    monkeypatch.setattr(panel, "_tco_matches_scenario", lambda *_: True)
    calls = []

    def unavailable(session, price):
        calls.append((session, price))
        return False

    monkeypatch.setattr(panel.consumption, "aws_price_current", unavailable)
    with pytest.raises(ValueError, match="aws_price_policy_not_current"):
        panel.build_decision_packet(graph.session, 1, raw_root=graph.tmp_path)
    assert calls == [(graph.session, graph.price)]
    graph.session.flush.assert_not_called()
    graph.session.commit.assert_not_called()
