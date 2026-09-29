"""Synthetic offline fixtures, never actual AWS approval or a business database."""

import copy
import json
import sqlite3
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event, func, inspect, select

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.source import Evidence
from cloud_expert.pricing import aws_document_catalog as documents
from cloud_expert.pricing import aws_price_replacement as replacement
from cloud_expert.pricing import price_lifecycle as lifecycle
from cloud_expert.pricing.aws_billing_policy import canonical, digest
from cloud_expert.pricing.aws_catalog_promotion import _price_values
from tests.unit.test_aws_document_catalog import seed
from tests.unit.test_official_catalog import NOW


def fixture_data(session, tmp_path, monkeypatch, old_id=13, *, two_tiers=False):
    sku_code, product, usage = replacement.SUPPORTED[old_id]
    data = seed(session, tmp_path, monkeypatch, product=product, tier=2 if old_id == 17 else 1)
    old_code = data.selection.sku
    payload = data.payload
    item = payload["products"].pop(old_code)
    attrs = item["attributes"]
    attrs["usagetype"] = usage
    if product == "ec2":
        attrs["instanceType"] = "m6i.xlarge"
    item["sku"] = sku_code
    payload["products"][sku_code] = item
    old_term = next(iter(payload["terms"]["OnDemand"].pop(old_code).values()))
    term_code = sku_code + ".JRTCKXETXF"
    old_term["sku"] = sku_code
    dimensions = list(old_term["priceDimensions"].values())
    old_term["priceDimensions"] = {}
    for index, dimension in enumerate(dimensions if two_tiers else dimensions[:1]):
        rate_code = f"{term_code}.TEST{index}"
        dimension["rateCode"] = rate_code
        if not two_tiers:
            dimension["endRange"] = "Inf"
        if product == "ec2":
            dimension["description"] = "$0.192 per On Demand Linux m6i.xlarge Instance Hour"
        old_term["priceDimensions"][rate_code] = dimension
    payload["terms"]["OnDemand"][sku_code] = {term_code: old_term}
    data.selection = data.selection.model_copy(update={"sku": sku_code, "attributes": attrs})
    data.rewrite_catalog()
    plan = data.plan()
    row = plan["rows"][0]
    sku = PriceSKU(**row["sku"])
    session.add(sku)
    session.flush()
    raw = json.loads(row["evidence"]["excerpt"])
    # Retired website policy does not exist in this fixture and must never be read.
    payload = {
        "rule_version": replacement.LEGACY_RULE,
        **plan["catalog"],
        **plan["context"],
        "catalog_record": raw["catalog_record"],
        "promotion_config": {
            "snapshot_id": data.snapshot.id,
            "policy_snapshot_id": 999999,
            "selections": [data.selection.model_dump(mode="json")],
            "max_age_days": 7,
        },
        "policy_evidence_references": [{"retired_website_policy": "not_admissible"}],
        "billing_unit": row["sku"]["billing_unit"],
        "billing_period": row["price"]["billing_period"],
        "tax_included": False,
        "requires_all_tiers": True,
    }
    excerpt = canonical(payload)
    proof = Evidence(
        source_document_id=data.snapshot.source_document_id,
        snapshot_record_id=data.snapshot.id,
        locator=row["evidence"]["locator"],
        parser_rule=replacement.LEGACY_RULE,
        evidence_type="json_path",
        excerpt=excerpt,
        content_hash=digest(excerpt),
        confidence=1,
        review_status="machine_extracted",
    )
    session.add(proof)
    session.flush()
    session.add(
        PriceSnapshot(
            id=old_id,
            price_sku_id=sku.id,
            evidence_id=proof.id,
            **_price_values(row),
            created_at=NOW - timedelta(minutes=30),
        )
    )
    session.commit()
    return data, plan, old_id


@pytest.fixture
def setup(session, tmp_path, monkeypatch):
    return fixture_data(session, tmp_path, monkeypatch)


def prepare(setup):
    data, docplan, old_id = setup
    return replacement.prepare_aws_price_replacement(
        data.session,
        old_price_id=old_id,
        document_plan=docplan,
        raw_root=data.root,
        as_of=NOW,
    )


def apply(setup, plan, *, write=True):
    data, _, _ = setup
    return replacement.apply_aws_price_replacement(
        data.session,
        plan,
        expected_plan_sha256=plan.plan_sha256,
        raw_root=data.root,
        apply=write,
        now=NOW,
    )


def verifier(setup):
    data, docplan, old_id = setup
    return replacement.AWSPriceReplacementVerifier(
        old_price_id=old_id,
        document_plan=docplan,
        raw_root=data.root,
    )


def counts(session):
    return tuple(
        session.scalar(select(func.count()).select_from(cls))
        for cls in (
            PriceSKU,
            PriceSnapshot,
            Evidence,
            ModelReviewRun,
            ModelReviewFinding,
            ModelReviewAssignment,
            ModelReviewAuditEvent,
        )
    )


def test_preview_is_read_only_and_legacy_is_not_current(setup):
    data, _, old_id = setup
    before = counts(data.session)
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(data.session.bind, "before_cursor_execute", observe)
    try:
        plan = prepare(setup)
        result = apply(setup, plan, write=False)
        assert not result["created"] and result["new_price_id"] is None
        assert counts(data.session) == before
        assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
    finally:
        event.remove(data.session.bind, "before_cursor_execute", observe)
    status = lifecycle.resolve_price(data.session, old_id, verifier=verifier(setup), now=NOW)
    assert status.status == "blocked" and not status.customer_eligible


@pytest.mark.parametrize("old_id", [13, 17, 18])
def test_exact_replacement_preserves_history_and_replays(session, tmp_path, monkeypatch, old_id):
    setup = fixture_data(session, tmp_path, monkeypatch, old_id)
    old = session.get(PriceSnapshot, old_id)
    old_state = lifecycle.price_fingerprint(session, old_id)
    before = counts(session)
    plan = prepare(setup)
    result = apply(setup, plan)
    new_id = result["new_price_id"]
    assert result["created"] and result["evidence_created"] == 1
    assert not result["transaction_committed"] and not result["price_approval"]
    assert not result["complete_tco"] and result["customer_payable_tax"] == "unknown"
    session.commit()
    new = session.get(PriceSnapshot, new_id)
    assert lifecycle.price_fingerprint(session, old_id) == old_state
    assert old.price_sku_id == new.price_sku_id and old.evidence_id != new.evidence_id
    for key in ("captured_at", "effective_from", "effective_to", "unit_price", "billing_period"):
        assert getattr(old, key) == getattr(new, key)
    assert new.evidence.parser_rule == documents.RULE
    status = lifecycle.resolve_price(session, old_id, verifier=verifier(setup), now=NOW)
    assert status.status == "superseded" and status.current_price_id == new_id
    assert (
        lifecycle.resolve_price(session, new_id, verifier=verifier(setup), now=NOW).status
        == "current"
    )
    after = counts(session)
    assert tuple(b - a for a, b in zip(before, after, strict=True)) == (0, 1, 1, 1, 1, 1, 1)
    replay = apply(setup, plan)
    session.commit()
    assert not replay["created"] and replay["new_price_id"] == new_id and counts(session) == after


@pytest.mark.parametrize("failure", ["caller", "lifecycle"])
def test_outer_transaction_and_lifecycle_failure_roll_back_new_facts(setup, monkeypatch, failure):
    data, _, old_id = setup
    before, original = counts(data.session), lifecycle.price_fingerprint(data.session, old_id)
    plan = prepare(setup)
    if failure == "caller":
        apply(setup, plan)
        data.session.rollback()
    else:
        original_apply = lifecycle.apply_replacement

        def failing(*args, **kwargs):
            original_apply(*args, **kwargs)
            raise ValueError("synthetic failure after lifecycle append")

        monkeypatch.setattr(lifecycle, "apply_replacement", failing)
        with pytest.raises(ValueError, match="synthetic failure"):
            apply(setup, plan)
        data.session.commit()
    assert counts(data.session) == before
    assert lifecycle.price_fingerprint(data.session, old_id) == original


@pytest.mark.parametrize(
    "kind", ["amount", "unit", "tax", "currency", "region", "effective", "parser", "payload"]
)
def test_old_cas_tamper_fails_without_successor(setup, kind):
    data, _, old_id = setup
    plan = prepare(setup)
    old = data.session.get(PriceSnapshot, old_id)
    if kind == "amount":
        old.unit_price = Decimal("10")
    elif kind == "unit":
        old.price_sku.billing_unit = "GB-month"
    elif kind == "tax":
        old.price_sku.tax_included = True
    elif kind == "currency":
        old.price_sku.currency = "CNY"
    elif kind == "region":
        old.price_sku.region.code = "other-region"
    elif kind == "effective":
        old.effective_from = NOW
    elif kind == "parser":
        old.evidence.parser_rule = "aws_s3_standard_storage_first_tier_v1"
    else:
        old.evidence.excerpt += " "
    data.session.commit()
    before = counts(data.session)
    with pytest.raises(ValueError, match="legacy_row_cas_conflict"):
        apply(setup, plan)
    data.session.rollback()
    assert counts(data.session) == before


@pytest.mark.parametrize("kind", ["catalog", "document", "revoke", "successor", "receipt"])
def test_live_resolution_and_retry_fail_on_tamper(setup, kind):
    data, _, old_id = setup
    plan = prepare(setup)
    result = apply(setup, plan)
    data.session.commit()
    if kind == "catalog":
        path = data.root / data.snapshot.storage_path
        path.write_bytes(b"x" * path.stat().st_size)
    elif kind == "document":
        ref = data.session.get(Evidence, data.references[0].evidence_id)
        path = data.root / ref.source_document.storage_path
        path.write_bytes(b"x" * path.stat().st_size)
    elif kind == "revoke":
        source = next(k for k in data.entries if "principles" in k)
        data.entries[source] = data.entries[source].model_copy(update={"enabled": False})
    elif kind == "successor":
        data.session.delete(data.session.get(PriceSnapshot, result["new_price_id"]))
    else:
        data.session.scalar(select(ModelReviewAuditEvent)).reason = "tampered"
    data.session.commit()
    before = counts(data.session)
    assert (
        lifecycle.resolve_price(data.session, old_id, verifier=verifier(setup), now=NOW).status
        == "blocked"
    )
    with pytest.raises(ValueError):
        apply(setup, plan)
    data.session.rollback()
    assert counts(data.session) == before


def test_historical_does_not_reauthorize_policies_but_current_needs_documents(setup):
    data, _, old_id = setup
    plan = prepare(setup)
    result = apply(setup, plan)
    data.session.commit()
    source = next(k for k in data.entries if "principles" in k)
    data.entries[source] = data.entries[source].model_copy(update={"enabled": False})
    check = verifier(setup)
    historical = check(data.session, (old_id,), purpose="historical", now=NOW)
    assert not historical.current_policy_verified and not historical.policy_evidence
    with pytest.raises(ValueError):
        check(data.session, (result["new_price_id"],), purpose="current", now=NOW)


@pytest.mark.parametrize("bad_id", [1, 14, 15, 16, 999])
def test_out_of_scope_legacy_ids_never_promoted(setup, bad_id):
    data, docplan, _ = setup
    with pytest.raises(ValueError, match="unsupported_legacy_price"):
        replacement.prepare_aws_price_replacement(
            data.session,
            old_price_id=bad_id,
            document_plan=docplan,
            raw_root=data.root,
            as_of=NOW,
        )


def test_partial_historical_tier_group_fails(session, tmp_path, monkeypatch):
    setup = fixture_data(session, tmp_path, monkeypatch, two_tiers=True)
    with pytest.raises(ValueError, match="incomplete_legacy_tier_group"):
        prepare(setup)


def test_wrong_expected_hash_and_rehashed_forged_plan_fail(setup):
    data, _, _ = setup
    plan = prepare(setup)
    with pytest.raises(ValueError, match="replacement_plan_hash_mismatch"):
        replacement.apply_aws_price_replacement(
            data.session,
            plan,
            expected_plan_sha256="0" * 64,
            raw_root=data.root,
            now=NOW,
        )
    forged = copy.deepcopy(plan.document_plan)
    forged["rows"][0]["price"]["unit_price"] = "9"
    forged["plan_sha256"] = digest(
        canonical({k: v for k, v in forged.items() if k != "plan_sha256"})
    )
    plan = plan.model_copy(update={"document_plan": forged})
    plan = plan.model_copy(update={"plan_sha256": replacement._hash(plan)})
    with pytest.raises(ValueError):
        apply(setup, plan)


def test_unreceipted_existing_successor_is_not_automatically_activated(setup):
    data, docplan, old_id = setup
    plan = prepare(setup)
    row = docplan["rows"][0]
    ev = replacement.evidence_row(data.session, row["evidence"], apply=True)
    old = data.session.get(PriceSnapshot, old_id)
    data.session.add(
        PriceSnapshot(
            **_price_values(row),
            price_sku_id=old.price_sku_id,
            evidence_id=ev.id,
            created_at=NOW,
        )
    )
    data.session.commit()
    with pytest.raises(ValueError, match="successor_without_replacement_receipt"):
        apply(setup, plan)
    data.session.rollback()
    assert data.session.scalar(select(func.count()).select_from(ModelReviewRun)) == 0
    for price in data.session.scalars(select(PriceSnapshot)):
        assert (
            replacement.aws_replacement_disposition(
                data.session,
                price,
                data.root,
                NOW,
            ).status
            == "blocked"
        )


@pytest.mark.parametrize("old_id", [13, 17, 18])
def test_public_disposition_decodes_only_receipt_bound_successor(
    session,
    tmp_path,
    monkeypatch,
    old_id,
):
    setup = fixture_data(session, tmp_path, monkeypatch, old_id)
    data, _, _ = setup
    old = session.get(PriceSnapshot, old_id)
    assert replacement.aws_replacement_disposition(session, old, data.root, NOW).status == "blocked"
    result = apply(setup, prepare(setup))
    session.commit()
    new = session.get(PriceSnapshot, result["new_price_id"])
    old_status = replacement.aws_replacement_disposition(session, old, data.root, NOW)
    new_status = replacement.aws_replacement_disposition(session, new, data.root, NOW)
    assert old_status.status == "superseded" and old_status.current_price_id == new.id
    assert new_status.status == "current" and new_status.current_price_id == new.id
    assert not old_status.customer_eligible and not new_status.customer_eligible


@pytest.mark.parametrize("pending", ["dirty", "new", "deleted"])
def test_disposition_rejects_pending_session_before_loading_expired_price_id(setup, pending):
    data, _, old_id = setup
    session = data.session
    session.autoflush = True
    price = session.get(PriceSnapshot, old_id)
    sku = price.price_sku
    session.expire(price)
    if pending == "dirty":
        sku.currency = "CNY"
    elif pending == "new":
        session.add(PriceSnapshot())
    else:
        session.delete(sku)
    assert "id" in inspect(price).expired_attributes
    before = (set(session.new), set(session.dirty), set(session.deleted))
    statements, flushes = [], []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def flush_observer(*args):
        flushes.append(True)

    event.listen(session.bind, "before_cursor_execute", observe)
    event.listen(session, "before_flush", flush_observer)
    try:
        result = replacement.aws_replacement_disposition(session, price, data.root, NOW)
        assert result.status == "blocked" and result.diagnostics == ("clean_session_required",)
        assert result.price_id == old_id and result.current_price_id is None
        assert not statements and not flushes
        assert "id" in inspect(price).expired_attributes
        assert (set(session.new), set(session.dirty), set(session.deleted)) == before
    finally:
        event.remove(session.bind, "before_cursor_execute", observe)
        event.remove(session, "before_flush", flush_observer)
        session.rollback()


@pytest.mark.parametrize(
    "kind", ["registry", "receipt", "missing_event", "config", "expired", "raw"]
)
def test_public_disposition_rechecks_current_dependencies(setup, kind):
    data, _, old_id = setup
    result = apply(setup, prepare(setup))
    data.session.commit()
    before = counts(data.session)
    now = NOW
    if kind == "registry":
        source = data.snapshot.source_id
        data.entries[source] = data.entries[source].model_copy(
            update={"compliance_notes": "SYNTHETIC changed authorization version"},
        )
    elif kind == "receipt":
        run = data.session.scalar(select(ModelReviewRun))
        payload = copy.deepcopy(run.summary_json)
        payload["plan"]["new"]["rates"][0]["price_id"] = old_id
        run.summary_json = payload
    elif kind == "missing_event":
        data.session.delete(data.session.scalar(select(ModelReviewAuditEvent)))
    elif kind == "config":
        ev = data.session.get(PriceSnapshot, result["new_price_id"]).evidence
        payload = json.loads(ev.excerpt)
        payload["derivation_config"]["snapshot_id"] = 99999
        ev.excerpt = canonical(payload)
        ev.content_hash = digest(ev.excerpt)
    elif kind == "expired":
        now += timedelta(days=8)
    else:
        path = data.root / data.snapshot.storage_path
        path.write_bytes(b"x" * path.stat().st_size)
    data.session.commit()
    after_mutation = counts(data.session)
    for price_id in (old_id, result["new_price_id"]):
        price = data.session.get(PriceSnapshot, price_id)
        disposition = replacement.aws_replacement_disposition(data.session, price, data.root, now)
        assert disposition.status == "blocked" and disposition.current_price_id is None
    assert counts(data.session) == after_mutation
    assert after_mutation[:6] == before[:6]


def test_cli_readonly_preview_immutable_reports_and_explicit_apply_hash(setup, monkeypatch):
    data, _, _ = setup
    plan = prepare(setup)
    data.session.commit()
    database = data.root / "synthetic_cli.sqlite"
    with data.session.bind.connect() as connection, sqlite3.connect(database) as target:
        connection.connection.driver_connection.backup(target)
    saved = data.root / "replacement_plan.json"
    saved.write_text(plan.model_dump_json(), encoding="utf-8")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import replace_aws_price_policy as script

    class Clock:
        @staticmethod
        def now(tz):
            return NOW

    monkeypatch.setattr(script, "datetime", Clock)
    base = [
        "replace_aws_price_policy.py",
        "--database",
        str(database),
        "--raw-root",
        str(data.root),
        "--plan",
        str(saved),
    ]
    report = data.root / "preview"
    monkeypatch.setattr(sys, "argv", [*base, "--report-dir", str(report)])
    before = database.read_bytes()
    assert script.main() == 0
    assert database.read_bytes() == before
    result = json.loads((report / "result.json").read_text(encoding="utf-8"))
    assert result["database_open_mode"] == "ro" and not result["transaction_committed"]
    assert result["network_requests"] == 0
    with pytest.raises(FileExistsError):
        script.main()
    assert database.read_bytes() == before
    applied_report = data.root / "apply"
    monkeypatch.setattr(sys, "argv", [*base, "--report-dir", str(applied_report), "--apply"])
    with pytest.raises(SystemExit) as failure:
        script.main()
    assert failure.value.code == 2 and not applied_report.exists()
    assert database.read_bytes() == before

    for directory in (applied_report, data.root / "retry"):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                *base,
                "--report-dir",
                str(directory),
                "--apply",
                "--expected-plan-sha256",
                plan.plan_sha256,
            ],
        )
        assert script.main() == 0
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        assert result["transaction_committed"] and result["database_open_mode"] == "rw"
        assert result["created"] is (directory == applied_report)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM price_snapshot").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM model_review_run").fetchone() == (1,)
