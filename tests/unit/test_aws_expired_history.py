"""Synthetic offline expiry fixtures; never business data or price approval."""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import aws_document_policy as policy
from cloud_expert.pricing import aws_expired_history as expiry
from cloud_expert.pricing import aws_price_replacement as replacement
from cloud_expert.pricing import price_lifecycle as life
from cloud_expert.pricing.aws_billing_policy import canonical, digest, verified_snapshot
from cloud_expert.pricing.official_catalog import inspect_official_catalog
from tests.unit.test_aws_price_replacement import fixture_data
from tests.unit.test_official_catalog import NOW

LATER = NOW + timedelta(days=8)


def seed_pair(session, tmp_path, monkeypatch, old_id=13):
    data, docplan, _ = fixture_data(session, tmp_path, monkeypatch, old_id)
    old = session.get(PriceSnapshot, old_id)
    new_id = expiry.PAIRS[old_id]
    # Reserve unrelated synthetic IDs so the receipt binds the explicit remediation pair.
    if new_id - 1 != old_id:
        fields = {
            k: v
            for k, v in life._row(old.price_sku).items()
            if k not in {"id", "created_at", "updated_at"}
        }
        fields["provider_price_code"] = "synthetic-reserved-id"
        fields["tax_included"] = False
        sku = PriceSKU(**fields)
        session.add(sku)
        session.flush()
        session.add(
            PriceSnapshot(
                id=new_id - 1,
                price_sku_id=sku.id,
                evidence_id=old.evidence_id,
                unit_price=1,
                minimum_quantity=0,
                maximum_quantity=None,
                billing_period=old.billing_period,
                discount_type="list",
                captured_at=NOW,
            )
        )
        session.commit()
    plan = replacement.prepare_aws_price_replacement(
        session, old_price_id=old_id, document_plan=docplan, raw_root=tmp_path, as_of=NOW
    )
    applied = replacement.apply_aws_price_replacement(
        session, plan, expected_plan_sha256=plan.plan_sha256, raw_root=tmp_path, apply=True, now=NOW
    )
    session.commit()
    assert applied["new_price_id"] == new_id
    return data, old_id, new_id


@pytest.fixture
def setup(session, tmp_path, monkeypatch):
    return seed_pair(session, tmp_path, monkeypatch)


def prepare(setup, at=LATER):
    data, old, new = setup
    return expiry.prepare_expired_history(data.session, [old, new], raw_root=data.root, now=at)


def apply(setup, plan, *, write=True, at=LATER):
    data, _, _ = setup
    return expiry.apply_expired_history(
        data.session, plan, expected_hash=plan.plan_sha256, raw_root=data.root, apply=write, now=at
    )


def disposition(setup, price_id=None, at=LATER):
    data, old, _ = setup
    return expiry.expired_history_disposition(
        data.session, data.session.get(PriceSnapshot, price_id or old), raw_root=data.root, now=at
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


@pytest.mark.parametrize("old_id", [13, 17, 18])
def test_expired_pair_preview_apply_replay(session, tmp_path, monkeypatch, old_id):
    setup = seed_pair(session, tmp_path, monkeypatch, old_id)
    data, old, new = setup
    before = counts(session)
    original = {i: life.price_fingerprint(session, i) for i in (old, new)}
    assert disposition(setup) is None
    plan = prepare(setup)
    preview = apply(setup, plan, write=False)
    assert not preview["applied"] and not preview["created"] and counts(session) == before
    result = apply(setup, plan)
    assert (
        result["created"] and result["approvals_granted"] == result["current_prices_granted"] == 0
    )
    session.commit()
    after = counts(session)
    assert tuple(b - a for a, b in zip(before, after, strict=True)) == (0, 0, 0, 1, 2, 2, 2)
    for i in (old, new):
        status = disposition(setup, i)
        assert (
            status.status == "expired_history"
            and status.current_price_id is None
            and not status.customer_eligible
        )
        assert life.price_fingerprint(session, i) == original[i]
    assert apply(setup, plan)["status"] == "already_recorded"
    session.commit()
    assert counts(session) == after


def test_boundary_and_current_wrappers_stay_strict(setup):
    data, old, new = setup
    # Fixture capture precedes NOW by one hour.
    earliest = data.snapshot.captured_at
    from cloud_expert.pricing.aws_billing_policy import utc

    at = utc(earliest) + timedelta(days=7)
    with pytest.raises(ValueError, match="not_expired"):
        prepare(setup, at)
    plan = prepare(setup, at + timedelta(microseconds=1))
    assert plan.groups[0].expires_at == at
    with pytest.raises(ValueError, match="freshness"):
        verified_snapshot(
            data.session, data.snapshot.id, raw_root=data.root, as_of=LATER, max_age_days=7
        )
    with pytest.raises(ValueError, match="stale"):
        inspect_official_catalog(
            canonical(data.payload).encode(),
            entry=data.entries[data.snapshot.source_id],
            manifest=json.loads((data.root / data.snapshot.manifest_path).read_bytes()),
            selections=[data.selection],
            as_of=LATER,
            max_age_days=7,
        )


@pytest.mark.parametrize(
    "kind",
    [
        "price",
        "currency",
        "tax",
        "raw",
        "manifest",
        "evidence",
        "missing_successor",
        "extra_tier",
        "policy",
        "source_permission",
    ],
)
@pytest.mark.parametrize("recorded", [False, True])
def test_mutations_never_become_verified_expiry(setup, kind, recorded):
    data, old_id, new_id = setup
    session = data.session
    plan = prepare(setup)
    if recorded:
        apply(setup, plan)
        session.commit()
    price = session.get(PriceSnapshot, new_id)
    if kind == "price":
        price.unit_price += Decimal("0.1")
    elif kind == "currency":
        price.price_sku.currency = "CNY"
    elif kind == "tax":
        price.price_sku.tax_included = True
    elif kind == "raw":
        (data.root / data.snapshot.storage_path).write_bytes(b"synthetic-tamper")
    elif kind == "manifest":
        (data.root / data.snapshot.manifest_path).write_text("{}", encoding="utf-8")
    elif kind == "evidence":
        price.evidence.excerpt += " "
    elif kind == "missing_successor":
        session.delete(price)
    elif kind == "extra_tier":
        session.add(
            PriceSnapshot(
                price_sku_id=price.price_sku_id,
                evidence_id=price.evidence_id,
                unit_price=price.unit_price,
                minimum_quantity=1,
                maximum_quantity=None,
                billing_period=price.billing_period,
                discount_type="list",
                captured_at=price.captured_at,
            )
        )
    elif kind == "policy":
        ev = session.get(Evidence, int(next(iter(plan.groups[0].evidence_sha256s))))
        ev.review_status = "rejected"
    else:
        data.entries[data.snapshot.source_id].enabled = False
    session.commit()
    if recorded:
        assert disposition(setup).status == "blocked"
    else:
        with pytest.raises(ValueError):
            apply(setup, plan)
        session.rollback()


@pytest.mark.parametrize("failure", ["caller", "append"])
def test_atomic_rollback(setup, monkeypatch, failure):
    data, _, _ = setup
    plan, before = prepare(setup), counts(data.session)
    if failure == "append":
        original = expiry._append

        def fail(*args):
            original(*args)
            raise ValueError("synthetic append failure")

        monkeypatch.setattr(expiry, "_append", fail)
        with pytest.raises(ValueError, match="synthetic append failure"):
            apply(setup, plan)
        data.session.commit()
    else:
        apply(setup, plan)
        data.session.rollback()
    assert counts(data.session) == before
    assert disposition(setup) is None


@pytest.mark.parametrize("ids", [[13], [19], [13, 19, 19], [1, 14], [14, 15, 16], [13, 20]])
def test_partial_or_unsupported_pair_rejected(setup, ids):
    data, _, _ = setup
    with pytest.raises(ValueError):
        expiry.prepare_expired_history(data.session, ids, raw_root=data.root, now=LATER)


@pytest.mark.parametrize(
    "kind",
    ["run_header", "event_header", "body", "missing_event", "missing_assignment", "orphan_event"],
)
def test_audit_corruption_never_falls_through(setup, kind):
    data, _, _ = setup
    apply(setup, prepare(setup))
    data.session.commit()
    run = data.session.scalar(
        select(ModelReviewRun).where(ModelReviewRun.policy_version == expiry.RULE)
    )
    ev = data.session.scalar(
        select(ModelReviewAuditEvent).where(ModelReviewAuditEvent.source == expiry.ACTOR)
    )
    if kind == "run_header":
        run.run_code = run.policy_version = run.reviewer_model = "damaged"
    elif kind == "event_header":
        ev.event_code = ev.source = "damaged"
    elif kind == "body":
        run.summary_json = {}
    elif kind == "missing_event":
        data.session.delete(ev)
    elif kind == "missing_assignment":
        assignment = data.session.get(ModelReviewAssignment, ev.assignment_id)
        data.session.delete(ev)
        data.session.flush()
        data.session.delete(assignment)
    else:
        ev2 = ModelReviewAuditEvent(
            assignment_id=ev.assignment_id,
            event_code="orphan",
            previous_status=None,
            new_status="expired",
            source=expiry.ACTOR,
            model_id=None,
            reason=expiry.RULE,
            affected_records=[],
            downstream_rebuild_required=True,
            timestamp=LATER,
        )
        data.session.add(ev2)
    data.session.commit()
    assert disposition(setup).status == "blocked"


def test_dirty_expired_identity_never_autoflushes(setup):
    data, old, _ = setup
    price = data.session.get(PriceSnapshot, old)
    data.session.expire(price)
    data.session.autoflush = True
    data.session.add(
        ModelReviewRun(
            run_code="synthetic-pending",
            policy_version="test",
            reviewer_model="test",
            input_fingerprint="0" * 64,
            reviewed_at=LATER,
            summary_json={},
        )
    )
    statements = []

    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(data.session.bind, "before_cursor_execute", observe)
    try:
        status = expiry.expired_history_disposition(
            data.session, price, raw_root=data.root, now=LATER
        )
        assert status.price_id == old and status.status == "blocked"
        assert not statements
    finally:
        event.remove(data.session.bind, "before_cursor_execute", observe)
        data.session.rollback()


def test_future_clock_and_hash_conflicts(setup):
    data, _, _ = setup
    plan = prepare(setup)
    with pytest.raises(ValueError, match="hash_mismatch"):
        expiry.apply_expired_history(
            data.session, plan, expected_hash="0" * 64, raw_root=data.root, apply=True, now=LATER
        )
    with pytest.raises(ValueError, match="from_future"):
        apply(setup, plan, at=NOW)
    apply(setup, plan)
    data.session.commit()
    assert disposition(setup, at=NOW).status == "blocked"


def archive_snapshot(data, snapshot_id, at):
    """Emulate SourceFetcher._record_success: append then retire both old flags."""
    session = data.session
    old = session.get(SnapshotRecord, snapshot_id)
    entry = data.entries[old.source_id]
    raw = (data.root / old.storage_path).read_bytes() + b"\n "
    stored = SnapshotStore(data.root).store(
        entry=entry,
        requested_url=entry.url,
        final_url=entry.url,
        http_status=200,
        content_type=old.content_type,
        content=raw,
        response_headers={},
        content_metadata={"synthetic": True},
        fetch_duration_ms=0,
        captured_at=at,
    )
    manifest = stored.manifest
    doc_fields = {
        col.name: getattr(old.source_document, col.name)
        for col in SourceDocument.__table__.columns
        if col.name not in {"id", "created_at"}
    }
    doc_fields.update(
        captured_at=at,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        is_current=True,
    )
    doc = SourceDocument(**doc_fields)
    session.add(doc)
    session.flush()
    successor = SnapshotRecord(
        source_document_id=doc.id,
        source_id=old.source_id,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        manifest_path=str(stored.manifest_path.relative_to(data.root)),
        content_type=old.content_type,
        content_length_bytes=len(raw),
        captured_at=at,
        previous_snapshot_id=old.id,
        change_status=manifest.change_status,
        is_current=True,
    )
    session.add(successor)
    old.is_current = old.source_document.is_current = False
    session.commit()
    return successor


def test_later_archive_and_unrelated_growth_preserve_expiry(setup):
    data, old, new = setup
    plan = prepare(setup)
    apply(setup, plan)
    data.session.commit()
    at = LATER + timedelta(hours=1)
    for baseline in plan.groups[0].snapshots:
        archive_snapshot(data, baseline.snapshot_id, at)
    # Extra unrelated extraction does not alter the exact referenced policy group.
    data.session.add(
        Evidence(
            source_document_id=data.snapshot.source_document_id,
            snapshot_record_id=data.snapshot.id,
            evidence_type="json_path",
            locator="synthetic:unrelated",
            parser_rule="synthetic_only",
            confidence=1,
            excerpt="synthetic",
            content_hash=digest("synthetic"),
            review_status="machine_extracted",
        )
    )
    data.session.commit()
    for price_id in (old, new):
        status = disposition(setup, price_id, at=at + timedelta(seconds=1))
        assert status.status == "expired_history", status
    assert not apply(setup, plan, at=at + timedelta(seconds=1))["created"]


@pytest.mark.parametrize(
    "mutation",
    [
        "no_descendant",
        "broken_previous",
        "later_raw",
        "old_raw",
        "old_identity",
        "reactivate",
        "two_current",
    ],
)
def test_archive_requires_real_later_integrity_chain(setup, mutation):
    data, _, _ = setup
    plan = prepare(setup)
    apply(setup, plan)
    data.session.commit()
    at = LATER + timedelta(hours=1)
    old = data.snapshot
    if mutation == "no_descendant":
        old.is_current = old.source_document.is_current = False
    else:
        new = archive_snapshot(data, old.id, at)
        if mutation == "broken_previous":
            new.previous_snapshot_id = None
        elif mutation == "later_raw":
            (data.root / new.storage_path).write_bytes(b"mutated")
        elif mutation == "old_raw":
            (data.root / old.storage_path).write_bytes(b"mutated")
        elif mutation == "old_identity":
            old.source_id = "unknown"
        elif mutation == "reactivate":
            new.is_current = new.source_document.is_current = False
            old.is_current = old.source_document.is_current = True
        else:
            old.is_current = old.source_document.is_current = True
    data.session.commit()
    assert disposition(setup, at=at + timedelta(seconds=1)).status == "blocked"


def test_archive_before_baseline_or_between_preview_apply_is_not_accepted(setup):
    data, _, _ = setup
    plan = prepare(setup)
    at = LATER + timedelta(hours=1)
    archive_snapshot(data, data.snapshot.id, at)
    with pytest.raises(ValueError, match="fingerprint_changed"):
        apply(setup, plan, at=at)
    data.session.rollback()
    with pytest.raises(ValueError, match="fingerprint_changed"):
        prepare(setup, at)


def reseal_original_times(data, *, proof_time=None, applied_time=None):
    """Adversarial fixture: reseal all audit headers, not just a mismatched JSON hash."""
    session = data.session
    run = session.scalar(
        select(ModelReviewRun).where(ModelReviewRun.policy_version == life.VERSION)
    )
    receipt = life.ReplacementReceipt.model_validate(copy.deepcopy(run.summary_json))
    old, new = receipt.plan.old, receipt.plan.new
    if proof_time is not None:
        old = old.model_copy(update={"checked_at": proof_time})
        new = new.model_copy(update={"checked_at": proof_time})
    plan = receipt.plan.model_copy(update={"old": old, "new": new})
    plan = plan.model_copy(update={"plan_sha256": life._plan_hash(plan)})
    at = applied_time or receipt.applied_at
    receipt = receipt.model_copy(update={"plan": plan, "applied_at": at})
    receipt = receipt.model_copy(update={"receipt_sha256": life._receipt_hash(receipt)})
    run.summary_json = receipt.model_dump(mode="json")
    run.run_code = life.RUN_PREFIX + plan.plan_sha256
    run.input_fingerprint = plan.plan_sha256
    run.reviewed_at = at
    finding = session.scalar(select(ModelReviewFinding).where(ModelReviewFinding.run_id == run.id))
    finding.input_hash, finding.rationale = plan.plan_sha256, receipt.receipt_sha256
    assignment = session.scalar(
        select(ModelReviewAssignment).where(ModelReviewAssignment.precheck_finding_id == finding.id)
    )
    assignment.input_hash = plan.plan_sha256
    assignment.created_at = assignment.updated_at = at
    ev = session.scalar(
        select(ModelReviewAuditEvent).where(ModelReviewAuditEvent.assignment_id == assignment.id)
    )
    ev.event_code = f"{life.RUN_PREFIX}{plan.plan_sha256}:{old.rates[0].price_id}"
    ev.timestamp = at
    ev.affected_records = life._event_records(receipt, old.rates[0].price_id, new.rates[0].price_id)
    session.commit()
    assert life._ledger(session)[0] == receipt


@pytest.mark.parametrize(
    "mode", ["proof_before_capture", "proof_after_expiry", "applied_after_expiry", "naive_proof"]
)
def test_resealed_original_review_outside_real_window_is_rejected(setup, mode):
    data, _, _ = setup
    if mode == "proof_before_capture":
        reseal_original_times(data, proof_time=NOW - timedelta(days=2))
    elif mode == "proof_after_expiry":
        reseal_original_times(
            data, proof_time=NOW + timedelta(days=7), applied_time=NOW + timedelta(days=7)
        )
    elif mode == "applied_after_expiry":
        reseal_original_times(data, applied_time=NOW + timedelta(days=7))
    else:
        reseal_original_times(data, proof_time=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="(outside_capture_validity_window|future_original_proof)"):
        prepare(setup)


def test_original_window_proof_is_checked_during_consumption_too(setup):
    data, _, _ = setup
    apply(setup, prepare(setup))
    data.session.commit()
    reseal_original_times(data, applied_time=NOW + timedelta(days=7))
    assert disposition(setup).status == "blocked"


def test_policy_current_wrapper_never_accepts_fact_only_expiry(setup):
    data, _, _ = setup
    for sid in data.document_snapshots.values():
        facts = policy.prepare_document_policy_facts(
            data.session, sid, raw_root=data.root, checked_at=LATER
        )
        assert facts["verification_purpose"] == "archived_facts_only"
        assert not facts["price_approval"] and not facts["tco_eligible"]
        with pytest.raises(ValueError, match="snapshot scope"):
            policy.prepare_document_policy(
                data.session, sid, raw_root=data.root, as_of=LATER, max_age_days=7
            )


def test_two_session_competing_plan_conflict_and_retry(setup):
    data, old, new = setup
    first = prepare(setup)
    with Session(data.session.bind, autoflush=False) as second:
        competing = expiry.prepare_expired_history(
            second, [old, new], raw_root=data.root, now=LATER + timedelta(seconds=1)
        )
        apply(setup, first)
        data.session.commit()
        with pytest.raises(ValueError, match="idempotency_conflict"):
            expiry.apply_expired_history(
                second,
                competing,
                expected_hash=competing.plan_sha256,
                raw_root=data.root,
                apply=True,
                now=LATER + timedelta(seconds=1),
            )
        second.rollback()
        result = expiry.apply_expired_history(
            second,
            first,
            expected_hash=first.plan_sha256,
            raw_root=data.root,
            apply=True,
            now=LATER + timedelta(seconds=1),
        )
        second.commit()
        assert not result["created"]


def test_resealed_expiry_plan_and_audit_cas_conflicts(setup):
    data, _, _ = setup
    plan = prepare(setup)
    changed = plan.model_copy(update={"expected_audit_sha256": "1" * 64})
    changed = changed.model_copy(update={"plan_sha256": expiry._hash(changed, "plan_sha256")})
    with pytest.raises(ValueError, match="audit_cas_conflict"):
        apply(setup, changed)
    data.session.rollback()
    group = plan.groups[0].model_copy(update={"facts_sha256": "1" * 64})
    changed = plan.model_copy(update={"groups": (group,)})
    changed = changed.model_copy(update={"plan_sha256": expiry._hash(changed, "plan_sha256")})
    with pytest.raises(ValueError, match="facts_cas_conflict"):
        apply(setup, changed)
    data.session.rollback()


def test_cli_default_readonly_and_hash_pinned_apply(setup, tmp_path, monkeypatch, capsys):
    data, old, new = setup
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "scripts"))
    import expire_aws_price_history as cli

    class Clock:
        @staticmethod
        def now(tz):
            return LATER

    monkeypatch.setattr(cli, "datetime", Clock)
    path = tmp_path / "synthetic.sqlite"
    data.session.commit()
    connection = data.session.connection().connection.driver_connection
    with sqlite3.connect(path) as destination:
        connection.backup(destination)
    original_hash = digest(path.read_bytes())
    output = tmp_path / "preview"
    base = ["expire_aws_price_history", "--database", str(path), "--raw-root", str(data.root)]
    monkeypatch.setattr(
        sys, "argv", [*base, "--price-ids", str(old), str(new), "--report-dir", str(output)]
    )
    assert cli.main() == 0
    assert digest(path.read_bytes()) == original_hash
    preview = json.loads((output / "result.json").read_bytes())
    assert preview["database_open_mode"] == "ro" and not preview["transaction_committed"]
    plan = json.loads((output / "plan.json").read_bytes())
    for suffix in ("apply", "retry"):
        target = tmp_path / suffix
        monkeypatch.setattr(
            sys,
            "argv",
            [
                *base,
                "--plan",
                str(output / "plan.json"),
                "--expected-plan-sha256",
                plan["plan_sha256"],
                "--report-dir",
                str(target),
                "--apply",
            ],
        )
        assert cli.main() == 0
        result = json.loads((target / "result.json").read_bytes())
        assert result["transaction_committed"] and result["created"] is (suffix == "apply")
    assert "customer_eligible" in capsys.readouterr().out
