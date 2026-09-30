"""Synthetic offline rejection fixtures. No real data or approval grants."""

import copy
import json
import sqlite3
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.ingestion.fetcher import SourceFetcher
from cloud_expert.ingestion.result import HttpFetchResult
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import aws_catalog_promotion as promotion
from cloud_expert.pricing import price_lifecycle as life
from cloud_expert.pricing import price_quarantine as q
from tests.unit.test_aws_catalog_promotion import seed as seed_catalog
from tests.unit.test_official_catalog import NOW, SKU, TERM


def seed(session, root, monkeypatch):
    data = seed_catalog(session, root, monkeypatch)
    snapshot = data["snapshot"]
    entry = data["entries"].pop(snapshot.source_id)
    entry = entry.model_copy(update={"source_id": "aws_s3_pricing_bulk_us_east_1"})
    data["entries"][entry.source_id] = entry
    snapshot.source_id = entry.source_id
    attrs = data["payload"]["products"][SKU]["attributes"]
    attrs.update(usagetype="TimedStorage-ByteHrs", location="US East (N. Virginia)")
    data["selection"] = data["selection"].model_copy(update={"attributes": attrs})
    dimensions = data["payload"]["terms"]["OnDemand"][SKU][TERM]["priceDimensions"]
    for dimension in dimensions.values():
        dimension["description"] = "SYNTHETIC ONLY standard storage test rate"
    raw = q.canonical(data["payload"]).encode()
    (root / snapshot.storage_path).write_bytes(raw)
    snapshot.content_hash = snapshot.source_document.content_hash = q.digest(raw)
    snapshot.content_length_bytes = len(raw)
    path = root / snapshot.manifest_path
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(
        source_id=entry.source_id,
        content_sha256=snapshot.content_hash,
        content_length_bytes=len(raw),
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(q, "get_entry_by_source_id", data["entries"].get)
    session.commit()
    plan = promotion.prepare_aws_catalog_promotion(
        session,
        snapshot_id=snapshot.id,
        policy_snapshot_id=data["policy"].id,
        selections=[data["selection"]],
        raw_root=root,
        as_of=NOW,
    )
    result = promotion.apply_aws_catalog_promotion(
        session, plan, raw_root=root, apply=True, now=NOW
    )
    storage_ids = [r["price_snapshot_id"] for r in result["links"]]
    original = q._record_from_aws_s3_dimension(
        sku=SKU,
        offer_term_code=TERM,
        rate_code=f"{TERM}.TEST0",
        dimension=dimensions[f"{TERM}.TEST0"],
        snapshot=snapshot,
        document=snapshot.source_document,
    )
    assert original is not None
    sku = PriceSKU(
        **{
            **plan["rows"][0]["sku"],
            "provider_price_code": original.provider_price_code,
            "billing_unit": "GB-month",
        }
    )
    session.add(sku)
    session.flush()
    ev = Evidence(
        source_document_id=snapshot.source_document_id,
        snapshot_record_id=snapshot.id,
        locator=original.evidence_locator,
        excerpt=original.evidence_excerpt,
        content_hash=q.digest(original.evidence_excerpt),
        parser_rule=original.parser_rule,
        evidence_type="json_path",
        confidence=1,
        review_status="machine_extracted",
    )
    session.add(ev)
    session.flush()
    first = PriceSnapshot(
        price_sku_id=sku.id,
        evidence_id=ev.id,
        unit_price=original.unit_price,
        minimum_quantity=original.minimum_quantity,
        maximum_quantity=original.maximum_quantity,
        billing_period="monthly",
        discount_type="list",
        captured_at=snapshot.captured_at,
        source_payload_path=snapshot.storage_path,
    )
    session.add(first)
    session.commit()
    policy = data["entries"]["aws_s3_pricing"]
    data["entries"]["aws_s3_pricing"] = policy.model_copy(
        update={
            "enabled": False,
            "allow_automated_fetch": False,
            "automated_fetch_allowed": False,
            "terms_review_status": "disallowed",
            "reviewed_at": NOW - timedelta(minutes=1),
        }
    )
    data.update(ids=sorted([*storage_ids, first.id]), first=first.id, storage_ids=storage_ids)
    return data


@pytest.fixture
def data(session, tmp_path, monkeypatch):
    return seed(session, tmp_path, monkeypatch)


def plan(session, data):
    return q.prepare_price_quarantine(session, data["ids"], raw_root=data["root"], now=NOW)


def apply(session, data, proposal, write=True):
    return q.apply_price_quarantine(
        session,
        proposal,
        expected_plan_sha256=proposal.plan_sha256,
        raw_root=data["root"],
        apply=write,
        now=NOW,
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


def disposition(session, data, price_id):
    return q.quarantine_disposition(
        session, session.get(PriceSnapshot, price_id), data["root"], NOW
    )


def clone_row(row, **overrides):
    values = {
        column.name: copy.deepcopy(getattr(row, column.name))
        for column in row.__table__.columns
        if column.name != "id"
    }
    return type(row)(**{**values, **overrides})


def append_synthetic_capture(session, data, key):
    """Exercise actual archival persistence, without fetching any external source."""
    old = data[key]
    entry = data["entries"][old.source_id]
    at = NOW - timedelta(hours=1)
    raw = (data["root"] / old.storage_path).read_bytes() + b"\n"
    store = SnapshotStore(data["root"])
    stored = store.store(
        entry=entry,
        requested_url=entry.url,
        final_url=old.source_document.url,
        http_status=200,
        content_type=old.content_type,
        content=raw,
        response_headers={},
        content_metadata={"synthetic": True},
        fetch_duration_ms=0,
        captured_at=at,
    )
    result = HttpFetchResult(
        requested_url=entry.url,
        final_url=old.source_document.url,
        status_code=200,
        headers={},
        content=raw,
        content_type=old.content_type,
        encoding="utf-8",
        started_at=at,
        completed_at=at,
        duration_ms=0,
        retry_count=0,
    )
    new_id = SourceFetcher(snapshot_store=store)._record_success(session, entry, result, stored)
    new = session.get(SnapshotRecord, new_id)
    assert new.id != old.id and new.previous_snapshot_id == old.id
    assert not old.is_current and not old.source_document.is_current
    assert new.is_current and new.source_document.is_current
    return new


def test_dryrun_no_writes_no_record_returns_none(session, data):
    before = counts(session)
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", observe)
    try:
        proposal = plan(session, data)
        result = apply(session, data, proposal, write=False)
        assert {p.reason for p in proposal.proofs} == {
            "incomplete_graduated_catalog_group",
            "withdrawn_storage_unit_policy",
        }
        assert (
            not result["created"]
            and not result["price_validated"]
            and result["approvals_granted"] == 0
        )
        assert counts(session) == before
        assert disposition(session, data, data["first"]) is None
        assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
    finally:
        event.remove(session.bind, "before_cursor_execute", observe)


def test_atomic_append_replay_keeps_facts_and_rejects_consumption(session, data):
    fingerprints = {i: life.price_fingerprint(session, i) for i in data["ids"]}
    before = counts(session)
    proposal = plan(session, data)
    result = apply(session, data, proposal)
    session.commit()
    assert result["created"] and not result["transaction_committed"]
    after = counts(session)
    assert tuple(b - a for a, b in zip(before, after, strict=True)) == (0, 0, 0, 1, 3, 3, 3)
    for i in data["ids"]:
        status = disposition(session, data, i)
        assert status.status == "quarantined" and status.current_price_id is None
        assert not status.customer_eligible and status.successor_id is None
        assert "replacement_price_and_cost_coverage_unresolved" in status.diagnostics
        assert life.price_fingerprint(session, i) == fingerprints[i]
    retry = apply(session, data, proposal)
    session.commit()
    assert not retry["created"] and retry["receipt_sha256"] == result["receipt_sha256"]
    assert counts(session) == after
    for audit in session.scalars(select(ModelReviewAuditEvent)):
        assert audit.model_id is None and audit.source == q.ACTOR and audit.new_status == q.STATE
    from cloud_expert.model_review.migration import review_queue_integrity

    assert review_queue_integrity(session)["invalid_assignments"] == 0
    assert review_queue_integrity(session)["missing_assignments"] == 0


@pytest.mark.parametrize("phase", ["before_apply", "after_apply"])
@pytest.mark.parametrize(
    "growth",
    ["catalog_capture", "policy_capture", "unreferenced_evidence", "other_sku", "replacement"],
)
def test_unrelated_growth_and_real_archival_transition_preserve_quarantine(
    session, data, growth, phase
):
    proposal = plan(session, data)
    if phase == "after_apply":
        apply(session, data, proposal)
        session.commit()
    first = session.get(PriceSnapshot, data["first"])
    old_fingerprint = life.price_fingerprint(session, first.id)
    if growth.endswith("capture"):
        new = append_synthetic_capture(
            session, data, "snapshot" if growth == "catalog_capture" else "policy"
        )
        if growth == "catalog_capture":
            # Same SKU/parser, but a distinct captured catalog and price group.
            ev = clone_row(
                first.evidence,
                snapshot_record_id=new.id,
                source_document_id=new.source_document_id,
            )
            session.add(ev)
            session.flush()
            session.add(clone_row(first, evidence_id=ev.id, captured_at=new.captured_at))
    elif growth == "unreferenced_evidence":
        session.add(clone_row(first.evidence, locator="synthetic-unrelated-evidence"))
    elif growth == "other_sku":
        sku = clone_row(first.price_sku, provider_price_code="synthetic-unrelated-sku")
        session.add(sku)
        session.flush()
        session.add(clone_row(first, price_sku_id=sku.id))
    else:
        # A new derivation on the same SKU/catalog is not part of the old parser group.
        # This synthetic row is not being validated or activated by quarantine.
        ev = clone_row(first.evidence, parser_rule="aws_document_catalog_derivation_v2")
        session.add(ev)
        session.flush()
        session.add(clone_row(first, evidence_id=ev.id))
    session.commit()
    if growth == "catalog_capture":
        assert life.price_fingerprint(session, first.id) != old_fingerprint
    assert q._proofs(session, tuple(data["ids"]), data["root"], NOW) == proposal.proofs
    result = apply(session, data, proposal)
    session.commit()
    assert result["created"] is (phase == "before_apply")
    for price_id in data["ids"]:
        status = disposition(session, data, price_id)
        assert status.status == "quarantined" and status.current_price_id is None
        assert not status.customer_eligible
    after = counts(session)
    retry = apply(session, data, proposal)
    session.commit()
    assert not retry["created"] and counts(session) == after


@pytest.mark.parametrize("failure", ["caller", "mid_append", "post_append_proof"])
def test_rollback_has_no_partial_audit_and_never_modifies_price(
    session, data, monkeypatch, failure
):
    proposal = plan(session, data)
    before = counts(session)
    if failure == "caller":
        apply(session, data, proposal)
        session.rollback()
    else:
        append = q._append

        def broken(session, receipt):
            append(session, receipt)
            if failure == "mid_append":
                raise ValueError("synthetic append failure")
            data["entries"]["aws_s3_pricing"] = data["entries"]["aws_s3_pricing"].model_copy(
                update={"terms_review_status": "approved"}
            )

        monkeypatch.setattr(q, "_append", broken)
        with pytest.raises(ValueError):
            apply(session, data, proposal)
        session.commit()
    assert counts(session) == before


@pytest.mark.parametrize(
    "kind",
    [
        "price",
        "catalog_raw",
        "policy_raw",
        "registry",
        "manifest",
        "new_price",
        "evidence",
        "source_identity",
        "snapshot_identity",
        "ambiguous_policy",
        "event",
        "receipt",
        "missing_event",
    ],
)
def test_changed_data_invalidates_entire_receipt_and_never_falls_through(session, data, kind):
    proposal = plan(session, data)
    apply(session, data, proposal)
    session.commit()
    price = session.get(PriceSnapshot, data["first"])
    if kind == "price":
        price.unit_price = Decimal("99")
    elif kind in {"catalog_raw", "policy_raw"}:
        snap = data["snapshot" if kind == "catalog_raw" else "policy"]
        path = data["root"] / snap.storage_path
        path.write_bytes(b"x" * path.stat().st_size)
    elif kind == "registry":
        data["entries"]["aws_s3_pricing"] = data["entries"]["aws_s3_pricing"].model_copy(
            update={"compliance_notes": "Synthetic new review"}
        )
    elif kind == "manifest":
        path = data["root"] / data["snapshot"].manifest_path
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif kind == "new_price":
        session.add(
            PriceSnapshot(
                price_sku_id=price.price_sku_id,
                evidence_id=price.evidence_id,
                unit_price=price.unit_price,
                minimum_quantity=price.minimum_quantity,
                maximum_quantity=price.maximum_quantity,
                billing_period=price.billing_period,
                captured_at=price.captured_at,
            )
        )
    elif kind == "evidence":
        ev = price.evidence
        ev.section_title = "Synthetic mutated original evidence"
    elif kind == "source_identity":
        data["snapshot"].source_document.title = "Synthetic mutated original source"
    elif kind == "snapshot_identity":
        data["snapshot"].normalization_version = "synthetic-mutated"
    elif kind == "ambiguous_policy":
        ref = session.scalar(
            select(Evidence).where(
                Evidence.snapshot_record_id == data["policy"].id,
                Evidence.excerpt.contains('"kind":"storage_unit"'),
            )
        )
        assert ref is not None
        session.add(clone_row(ref))
    elif kind == "event":
        session.scalar(select(ModelReviewAuditEvent)).new_status = "model_approved"
    elif kind == "receipt":
        run = session.scalar(select(ModelReviewRun))
        payload = copy.deepcopy(run.summary_json)
        payload["receipt_sha256"] = "0" * 64
        run.summary_json = payload
    else:
        session.delete(session.scalar(select(ModelReviewAuditEvent)))
    session.commit()
    before = counts(session)
    for i in data["ids"]:
        assert disposition(session, data, i).status == "blocked"
    with pytest.raises(ValueError):
        apply(session, data, proposal)
    session.rollback()
    assert counts(session) == before


@pytest.mark.parametrize("change", ["missing", "duplicate", "added_tier", "moved_group"])
def test_original_group_membership_stays_strict_after_archival(session, data, change):
    proposal = plan(session, data)
    apply(session, data, proposal)
    session.commit()
    newer = append_synthetic_capture(session, data, "snapshot")
    target = session.get(PriceSnapshot, data["storage_ids"][-1])
    if change == "missing":
        session.delete(target)
    elif change == "duplicate":
        session.add(clone_row(target))
    elif change == "added_tier":
        ev = clone_row(target.evidence, locator=target.evidence.locator + ".SYNTHETIC_EXTRA")
        session.add(ev)
        session.flush()
        session.add(clone_row(target, evidence_id=ev.id, minimum_quantity=Decimal("99999")))
    else:
        target.evidence.snapshot_record_id = newer.id
        target.evidence.source_document_id = newer.source_document_id
    session.commit()
    assert disposition(session, data, data["first"]).status == "blocked"
    before = counts(session)
    with pytest.raises(ValueError):
        apply(session, data, proposal)
    session.rollback()
    assert counts(session) == before


@pytest.mark.parametrize("remaining_anchor", ["all", "receipt_body", "finding", "event_body"])
def test_corrupted_header_selectors_cannot_hide_existing_quarantine(
    session, data, remaining_anchor
):
    proposal = plan(session, data)
    apply(session, data, proposal)
    session.commit()
    run = session.scalar(select(ModelReviewRun))
    run.run_code = "SYNTHETIC_CORRUPTED_HEADER"
    run.reviewer_model = run.policy_version = "synthetic_corrupted"
    if remaining_anchor in {"finding", "event_body"}:
        run.summary_json = {}
    if remaining_anchor in {"receipt_body", "event_body"}:
        for finding in session.scalars(select(ModelReviewFinding)):
            finding.verdict = finding.reason_code = "synthetic_corrupted"
    for audit in session.scalars(select(ModelReviewAuditEvent)):
        audit.source = "synthetic_corrupted"
        audit.event_code = f"SYNTHETIC_CORRUPTED_{audit.id}"
        if remaining_anchor in {"receipt_body", "finding"}:
            audit.affected_records = []
    session.commit()
    before = counts(session)
    for price_id in data["ids"]:
        status = disposition(session, data, price_id)
        assert status is not None and status.status == "blocked"
        assert status.current_price_id is None and not status.customer_eligible
    with pytest.raises(ValueError):
        plan(session, data)
    with pytest.raises(ValueError):
        apply(session, data, proposal)
    session.rollback()
    assert counts(session) == before


@pytest.mark.parametrize(
    "kind",
    [
        "unknown_parser",
        "approved_policy",
        "pending_policy",
        "raw_hash",
        "partial_group",
        "wrong_provider",
    ],
)
def test_unsupported_or_unproven_is_not_terminal_quarantine(session, data, kind):
    if kind == "unknown_parser":
        session.get(PriceSnapshot, data["first"]).evidence.parser_rule = "unknown"
    elif kind.endswith("policy"):
        state = "approved" if kind == "approved_policy" else "pending_review"
        data["entries"]["aws_s3_pricing"] = data["entries"]["aws_s3_pricing"].model_copy(
            update={"terms_review_status": state}
        )
    elif kind == "raw_hash":
        session.get(PriceSnapshot, data["first"]).evidence.content_hash = "f" * 64
    elif kind == "partial_group":
        data["ids"] = data["storage_ids"][:1]
    else:
        data["provider"].code = "not-aws"
    session.commit()
    before = counts(session)
    with pytest.raises(ValueError):
        plan(session, data)
    assert counts(session) == before


@pytest.mark.parametrize("pending", ["dirty", "new", "deleted"])
def test_expired_id_never_autoflushes_pending_session(session, data, pending):
    price = session.get(PriceSnapshot, data["first"])
    sku = price.price_sku
    session.expire(price)
    if pending == "dirty":
        sku.currency = "CNY"
    elif pending == "new":
        session.add(PriceSnapshot())
    else:
        session.delete(sku)
    queries = []

    def observer(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(session.bind, "before_cursor_execute", observer)
    try:
        result = q.quarantine_disposition(session, price, data["root"], NOW)
        assert result.status == "blocked" and result.diagnostics == ("clean_session_required",)
        assert (
            result.price_id == data["first"]
            and not queries
            and "id" in inspect(price).expired_attributes
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", observer)
        session.rollback()


def test_two_sqlite_connections_lock_then_retry_idempotently(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'synthetic.sqlite').as_posix()}", connect_args={"timeout": 0.01}
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as a, Session(engine) as b:
            data = seed(a, tmp_path, monkeypatch)
            proposal = plan(a, data)
            result = apply(a, data, proposal)
            with pytest.raises(OperationalError):
                apply(b, data, proposal)
            b.rollback()
            a.commit()
            retry = apply(b, data, proposal)
            b.commit()
            assert not retry["created"] and retry["receipt_sha256"] == result["receipt_sha256"]
            assert counts(b)[3:] == (1, 3, 3, 3)
    finally:
        engine.dispose()


def test_overlapping_saved_plans_cannot_append_a_second_disposition(session, data):
    all_prices = plan(session, data)
    first_only = q.prepare_price_quarantine(
        session,
        [data["first"]],
        raw_root=data["root"],
        now=NOW,
    )
    apply(session, data, first_only)
    session.commit()
    before = counts(session)
    with pytest.raises(ValueError, match="quarantine_audit_cas_conflict"):
        apply(session, data, all_prices)
    session.rollback()
    assert counts(session) == before
    assert disposition(session, data, data["first"]).status == "quarantined"
    assert disposition(session, data, data["storage_ids"][0]) is None


def test_legacy_insert_timestamp_is_bound_for_rejection_without_rewriting(session, data):
    price = session.get(PriceSnapshot, data["first"])
    original_capture = q.utc(data["snapshot"].captured_at)
    inserted_at = original_capture + timedelta(seconds=2)
    price.captured_at = price.created_at = inserted_at
    price.source_payload_path = str((data["root"] / data["snapshot"].storage_path).resolve())
    session.commit()
    before = life.price_fingerprint(session, price.id)
    proposal = plan(session, data)
    apply(session, data, proposal)
    session.commit()
    assert disposition(session, data, data["first"]).status == "quarantined"
    assert life.price_fingerprint(session, price.id) == before
    assert q.utc(price.captured_at) == q.utc(price.created_at) == inserted_at
    assert q.utc(data["snapshot"].captured_at) == original_capture
    price.captured_at = price.created_at = inserted_at + timedelta(seconds=1)
    session.commit()
    assert disposition(session, data, data["first"]).status == "blocked"


@pytest.mark.parametrize(
    "kind", ["different_created", "before_source", "future", "wrong_path", "relative_path"]
)
def test_unproven_legacy_timestamp_exception_is_rejected(session, data, kind):
    price = session.get(PriceSnapshot, data["first"])
    capture = q.utc(data["snapshot"].captured_at)
    price.captured_at = price.created_at = capture + timedelta(seconds=2)
    price.source_payload_path = str((data["root"] / data["snapshot"].storage_path).resolve())
    if kind == "different_created":
        price.created_at = capture + timedelta(seconds=3)
    elif kind == "before_source":
        price.captured_at = price.created_at = capture - timedelta(seconds=1)
    elif kind == "future":
        price.captured_at = price.created_at = NOW + timedelta(seconds=1)
    elif kind == "wrong_path":
        price.source_payload_path = str((data["root"] / "unrelated_raw.bin").resolve())
    else:
        price.source_payload_path = data["snapshot"].storage_path
    session.commit()
    before = counts(session)
    with pytest.raises(ValueError, match="unsupported_legacy_capture_timestamp"):
        plan(session, data)
    assert counts(session) == before


def test_catalog_rows_still_require_exact_snapshot_capture_time(session, data):
    price = session.get(PriceSnapshot, data["storage_ids"][0])
    price.captured_at = price.created_at = q.utc(data["snapshot"].captured_at) + timedelta(
        seconds=2
    )
    price.source_payload_path = str((data["root"] / data["snapshot"].storage_path).resolve())
    session.commit()
    with pytest.raises(ValueError, match="stored_catalog_rate_mismatch"):
        plan(session, data)


def test_hash_apply_and_cli_readonly_immutable_report(session, data, monkeypatch):
    proposal = plan(session, data)
    with pytest.raises(ValueError, match="quarantine_plan_hash_mismatch"):
        q.apply_price_quarantine(
            session, proposal, expected_plan_sha256="0" * 64, raw_root=data["root"], now=NOW
        )
    session.commit()
    database = data["root"] / "synthetic_cli.sqlite"
    with session.bind.connect() as connection, sqlite3.connect(database) as target:
        connection.connection.driver_connection.backup(target)
    saved = data["root"] / "plan.json"
    saved.write_text(proposal.model_dump_json(), encoding="utf-8")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import quarantine_invalid_prices as script

    class Clock:
        @staticmethod
        def now(tz):
            return NOW

    monkeypatch.setattr(script, "datetime", Clock)
    base = [
        "quarantine_invalid_prices.py",
        "--database",
        str(database),
        "--raw-root",
        str(data["root"]),
        "--plan",
        str(saved),
    ]
    report = data["root"] / "preview"
    monkeypatch.setattr(sys, "argv", [*base, "--report-dir", str(report)])
    before = database.read_bytes()
    assert script.main() == 0 and database.read_bytes() == before
    assert (
        json.loads((report / "result.json").read_text(encoding="utf-8"))["database_open_mode"]
        == "ro"
    )
    with pytest.raises(FileExistsError):
        script.main()
    for name in ("apply", "retry"):
        out = data["root"] / name
        monkeypatch.setattr(
            sys,
            "argv",
            [
                *base,
                "--report-dir",
                str(out),
                "--apply",
                "--expected-plan-sha256",
                proposal.plan_sha256,
            ],
        )
        assert script.main() == 0
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        assert result["transaction_committed"] and result["created"] is (name == "apply")
