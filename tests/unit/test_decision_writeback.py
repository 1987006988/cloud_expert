"""Synthetic databases and mocked CLI artifacts only. No actual models or business DB."""

import hashlib
import json
import runpy
import sqlite3
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    NormalizationRule,
    NormalizedSpecification,
)
from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionReview
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.model_review import decision_panel as panel
from cloud_expert.model_review import decision_writeback as wb
from tests.unit import test_decision_panel as panel_tests
from tests.unit.test_decision_supersession import assignment, seed


def write_json(path, value):
    if path.exists():
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
    path.write_text(panel._json(value), encoding="utf-8")


def rehash(root):
    manifest = json.loads((root / "manifest.json").read_bytes())
    hashes = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    manifest.update(artifact_sha256=hashes, artifact_set_sha256=panel._hash(hashes))
    write_json(root / "manifest.json", manifest)


@pytest.fixture
def setup(session, tmp_path, monkeypatch):
    _, _, old, result, old_assignment = seed(session)
    result_id = result.id
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "synthetic-codex-home"))
    panel_tests._install_synthetic_runtime(monkeypatch, tmp_path)
    calls = []
    extra_records = []

    def packet(db_session, candidate_id, **kwargs):
        row = db_session.get(CandidateDecisionResult, candidate_id)
        payload = {
            "target_id": candidate_id,
            "evidence": [{"evidence_id": 1}],
            "data_classification": "official_public",
            "synthetic_test_only": True,
            "review_scope": panel.SCOPED_REVIEW,
            "limitations": list(panel.SCOPED_LIMITATIONS),
        }
        manifest = {
            "records": [panel._row_digest(row)]
            + [
                panel._row_digest(db_session.get(model, record_id))
                for model, record_id in extra_records
            ],
            "public_payload_sha256": panel._hash(payload),
        }
        fingerprint = panel._hash(manifest)
        payload["input_fingerprint"] = fingerprint
        return panel.DecisionPacket(
            panel._json(payload), panel._json(manifest), fingerprint, datetime.now(UTC).isoformat()
        )

    monkeypatch.setattr(panel, "build_decision_packet", packet)
    monkeypatch.setattr(panel, "probe_codex_cli", lambda *_: {"available": True, "exit_code": 0})
    original = panel_tests._opinion

    def make(*, decisions=None, conditions=None):
        def opinion(packet, stage="primary", **kwargs):
            return original(
                packet,
                stage,
                target_id=result_id,
                approved_scope=panel.SCOPED_REVIEW,
                limitations=list(panel.SCOPED_LIMITATIONS),
                decision=(decisions or {}).get(stage, "model_approved"),
                conditions=(conditions or {}).get(stage, []),
            )

        monkeypatch.setattr(panel_tests, "_opinion", opinion)
        calls.extend(panel_tests._cli_stub(monkeypatch, packet(session, result_id)))
        auth = yaml.safe_load((wb.CONFIG / "review_authorization.yaml").read_text(encoding="utf-8"))
        result_summary = panel.run_decision_panel(
            session, result_id, tmp_path / "reports", execute_models=True, authorization=auth
        )
        assert result_summary["status"] == "completed", result_summary
        session.rollback()
        return Path(result_summary["report_dir"])

    root = make()
    return SimpleNamespace(
        root=root,
        target_id=result_id,
        old_id=old.id,
        old_assignment_id=old_assignment.id,
        make=make,
        packet=packet,
        extra_records=extra_records,
    )


def counts(session):
    return tuple(
        session.scalar(select(func.count()).select_from(model))
        for model in (
            ModelReviewRun,
            ModelReviewFinding,
            ModelReviewAssignment,
            ModelReviewAuditEvent,
            DecisionReview,
        )
    )


def plan(session, setup):
    value = wb.plan_decision_panel(session, setup.root)
    session.rollback()
    return value


def apply(session, value):
    return wb.apply_decision_panel(
        session, value, apply=True, parent_reviewed_plan_sha256=value.plan_sha256
    )


def test_dry_run_never_writes_or_promotes(session, setup):
    before = counts(session)
    value = plan(session, setup)
    result = wb.apply_decision_panel(session, value)
    assert counts(session) == before
    assert result["records_appended"] == 0 and not result["applied"]
    assert not result["customer_eligible"] and not result["human_review"]
    assert value.receipt["review_scope"] == panel.SCOPED_REVIEW
    assert value.as_dict()["parent_review_required"]
    assert set(value.receipt["stages"]) == {"primary", "adversarial"}


def test_native_permissions_rechecked_before_local_metadata_exemption(session, setup, monkeypatch):
    native = setup.root / "primary/runtime.native.jsonl"
    original_bytes = native.read_bytes()
    original_verify = wb.verify_local_artifact
    checked = []

    def public_permissions(path):
        checked.append(path)
        if path == native:
            raise wb.RuntimeIsolationError("synthetic_public_permissions")
        return original_verify(path)

    monkeypatch.setattr(wb, "verify_local_artifact", public_permissions)
    scan = Mock(wraps=panel._runtime_sensitivity)
    monkeypatch.setattr(panel, "_runtime_sensitivity", scan)
    before = counts(session)
    with pytest.raises(wb.DecisionWritebackConflict, match="runtime_artifact_permissions_invalid"):
        plan(session, setup)
    session.rollback()
    assert checked == [native]
    assert counts(session) == before
    assert native.read_bytes() == original_bytes
    assert not any(
        call.kwargs.get("verified_isolated_native", False) for call in scan.call_args_list
    )


@pytest.mark.parametrize("field", ["identity_verified", "isolated_home_used"])
@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_privacy_receipt_requires_verified_isolated_native(session, setup, field, value):
    path = setup.root / "primary/privacy.json"
    privacy = json.loads(path.read_bytes())
    privacy[field] = value
    write_json(path, privacy)
    rehash(setup.root)
    before = counts(session)
    with pytest.raises(wb.DecisionWritebackConflict, match="privacy_receipt_invalid"):
        plan(session, setup)
    session.rollback()
    assert counts(session) == before


def test_append_preserve_history_idempotence_and_consume(session, setup):
    original = wb._row(session.get(CandidateDecisionResult, setup.target_id))
    historical = wb._row(session.get(ModelReviewAssignment, setup.old_assignment_id))
    before = counts(session)
    value = plan(session, setup)
    outcome = apply(session, value)
    assert outcome["records_appended"] == 5
    assert outcome["transaction_committed"] is False
    session.commit()
    assert counts(session) == tuple(n + 1 for n in before)
    assert wb._row(session.get(CandidateDecisionResult, setup.target_id)) == original
    assert wb._row(session.get(ModelReviewAssignment, setup.old_assignment_id)) == historical
    review = session.scalar(select(DecisionReview))
    assert review.reviewer == "model:gpt-6-astra"
    assert review.decision == "internally_approved"
    assert json.loads(review.notes) == value.receipt
    for stage in ("primary", "adversarial"):
        assert (
            value.receipt["stages"][stage]["raw_response"]
            == (setup.root / stage / "response.raw.json").read_bytes().decode()
        )
    session.rollback()
    again = apply(session, value)
    assert again["already_applied"] and again["records_appended"] == 0
    session.commit()
    assert counts(session) == tuple(n + 1 for n in before)
    approval = wb.current_internal_decision_approval(
        session, setup.target_id, scope=panel.SCOPED_REVIEW
    )
    assert approval is not None
    assert approval["customer_eligible"] is False and approval["rank_authorized"] is False
    assert approval["human_review"] is False and approval["model_version_gate_passed"] is False
    assert (
        wb.current_internal_decision_approval(session, setup.target_id, scope="customer_output")
        is None
    )


@pytest.mark.parametrize(
    "mode", ["missing_parent", "wrong_parent", "existing_transaction", "dirty"]
)
def test_apply_requires_controlled_fresh_session(session, setup, mode):
    value = plan(session, setup)
    parent_hash = value.plan_sha256
    if mode == "missing_parent":
        parent_hash = None
    elif mode == "wrong_parent":
        parent_hash = "0" * 64
    elif mode == "existing_transaction":
        session.scalar(select(CandidateDecisionResult.id))
    else:
        session.get(
            CandidateDecisionResult, setup.target_id
        ).explanation = "Unflushed synthetic edit"
    with pytest.raises(wb.DecisionWritebackConflict):
        wb.apply_decision_panel(session, value, apply=True, parent_reviewed_plan_sha256=parent_hash)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(DecisionReview)) == 0


def test_input_changes_block_apply_and_each_consumer_use(session, setup):
    value = plan(session, setup)
    session.get(CandidateDecisionResult, setup.target_id).explanation = "Changed synthetic facts"
    session.commit()
    with pytest.raises(wb.DecisionWritebackConflict, match="current_input_changed"):
        apply(session, value)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(DecisionReview)) == 0


@pytest.mark.parametrize(
    "change",
    [
        "input",
        "expiry",
        "new_review",
        "new_assignment",
        "assignment_state",
        "notes",
        "scope",
        "audit",
    ],
)
def test_consumer_fails_closed_after_change(session, setup, change):
    value = plan(session, setup)
    apply(session, value)
    session.commit()
    now = None
    if change == "input":
        session.get(CandidateDecisionResult, setup.target_id).explanation = "Changed live input"
    elif change == "expiry":
        now = datetime.now(UTC) + timedelta(hours=25)
    elif change == "new_review":
        session.add(
            DecisionReview(
                candidate_result_id=setup.target_id,
                reviewer="model:synthetic",
                reviewed_at=datetime.now(UTC),
                decision="rejected",
                notes="New disposition",
            )
        )
    elif change == "new_assignment":
        assignment(session, session.get(CandidateDecisionResult, setup.target_id), suffix="later")
    elif change == "assignment_state":
        row = session.scalar(
            select(ModelReviewAssignment).where(ModelReviewAssignment.target_id == setup.target_id)
        )
        row.review_state = "superseded"
    elif change == "notes":
        session.scalar(select(DecisionReview)).notes = "{}"
    elif change == "scope":
        session.scalar(select(DecisionReview)).approved_scope = {"review_scope": "customer_output"}
    else:
        session.scalar(
            select(ModelReviewAuditEvent).where(ModelReviewAuditEvent.source == wb.SOURCE)
        ).model_id = "weaker"
    session.commit()
    assert (
        wb.current_internal_decision_approval(
            session, setup.target_id, scope=panel.SCOPED_REVIEW, now=now
        )
        is None
    )


def test_new_history_conflicts_with_parent_reviewed_plan(session, setup):
    value = plan(session, setup)
    assignment(session, session.get(CandidateDecisionResult, setup.target_id), suffix="pending")
    session.commit()
    with pytest.raises(wb.DecisionWritebackConflict, match="review_history_changed"):
        apply(session, value)
    session.rollback()


def test_atomic_savepoint_rollback_and_caller_rollback(session, setup, monkeypatch):
    before = counts(session)
    value = plan(session, setup)
    original = wb._append

    def fail(*args):
        original(*args)
        raise RuntimeError("Synthetic post-insert failure")

    monkeypatch.setattr(wb, "_append", fail)
    with pytest.raises(RuntimeError):
        apply(session, value)
    assert counts(session) == before
    session.rollback()
    monkeypatch.setattr(wb, "_append", original)
    apply(session, value)
    session.rollback()
    assert counts(session) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "ready_not_executed"),
        ("model_calls_executed", False),
        ("customer_eligible", True),
        ("aggregate_gate_updated", True),
        ("model_id", "weaker-model"),
        ("model_version_gate_passed", True),
        ("authorization_sha256", "0" * 64),
        ("registry_sha256", "0" * 64),
        ("reproducibility_policy_sha256", "0" * 64),
        ("report_expires_at", "2020-01-01T00:00:00+00:00"),
        ("final_decision", "model_blocked"),
    ],
)
def test_rehashed_invalid_summary_cannot_approve(session, setup, field, value):
    summary_path = setup.root / "summary.json"
    summary = json.loads(summary_path.read_bytes())
    summary[field] = value
    write_json(summary_path, summary)
    rehash(setup.root)
    with pytest.raises(ValueError):
        plan(session, setup)


@pytest.mark.parametrize(
    "kind",
    ["raw", "payload", "extra", "traversal", "duplicate_key", "schema", "native", "identity"],
)
def test_tampering_cannot_approve(session, setup, kind):
    if kind == "raw":
        path = setup.root / "primary/response.raw.json"
        write_json(path, {})  # Keep original hash to test byte-integrity gate.
    elif kind == "payload":
        path = setup.root / "input.json"
        data = json.loads(path.read_bytes())
        data["target_id"] += 1
        write_json(path, data)
        rehash(setup.root)
    elif kind == "extra":
        write_json(setup.root / "unlisted.json", {})
    elif kind == "traversal":
        path = setup.root / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["artifact_sha256"]["../outside.json"] = "0" * 64
        write_json(path, manifest)
    elif kind == "duplicate_key":
        path = setup.root / "summary.json"
        raw = path.read_text(encoding="utf-8")
        path.write_text('{"status":"completed",' + raw[1:], encoding="utf-8")
        rehash(setup.root)
    else:
        filename = {
            "schema": "schema.json",
            "native": "runtime.native.jsonl",
            "identity": "execution.json",
        }[kind]
        path = setup.root / "primary" / filename
        if kind == "native":
            path.chmod(stat.S_IREAD | stat.S_IWRITE)
            raw = path.read_text(encoding="utf-8").replace(
                '"model": "gpt-6-astra"', '"model": "weaker"'
            )
            path.write_text(raw, encoding="utf-8")
        else:
            value = json.loads(path.read_bytes())
            value["type" if kind == "schema" else "actual_model_id"] = "weaker"
            write_json(path, value)
        # Also forge references and outer hashes; execution/native checks still reject.
        write_json(
            setup.root / "primary/artifacts.json", panel._stage_artifacts(setup.root / "primary")
        )
        rehash(setup.root)
    with pytest.raises(ValueError):
        plan(session, setup)


def test_conditions_must_be_enforceable_and_arbitration_retained(session, setup):
    setup.root = setup.make(
        decisions={
            "primary": "model_approved_with_conditions",
            "adversarial": "model_approved_with_conditions",
            "arbitration": "model_approved_with_conditions",
        },
        conditions={
            "primary": [panel.SCOPED_LIMITATIONS[0]],
            "adversarial": [panel.SCOPED_LIMITATIONS[1]],
            "arbitration": list(panel.SCOPED_LIMITATIONS[:2]),
        },
    )
    value = plan(session, setup)
    assert set(value.receipt["stages"]) == set(wb.STAGES)
    assert value.receipt["decision"] == "model_approved_with_conditions"
    apply(session, value)
    session.commit()
    assert wb.current_internal_decision_approval(
        session, setup.target_id, scope=panel.SCOPED_REVIEW
    )


def test_unknown_conditions_block_approval(session, setup):
    setup.root = setup.make(
        decisions=dict.fromkeys(wb.STAGES[:2], "model_approved_with_conditions"),
        conditions=dict.fromkeys(wb.STAGES[:2], ["Verify future region availability manually"]),
    )
    with pytest.raises(wb.DecisionWritebackConflict, match="unenforceable_conditions"):
        plan(session, setup)


@pytest.mark.parametrize(
    "verdict", ["model_blocked", "model_rejected_reparse", "model_inconclusive"]
)
def test_nonapproval_is_preserved_but_never_consumed(session, setup, verdict):
    setup.root = setup.make(decisions=dict.fromkeys(wb.STAGES[:2], verdict))
    value = plan(session, setup)
    apply(session, value)
    session.commit()
    row = session.scalar(select(DecisionReview))
    assert row.decision == ("machine_generated" if verdict == "model_inconclusive" else "rejected")
    assert json.loads(row.notes)["decision"] == verdict
    assert (
        wb.current_internal_decision_approval(session, setup.target_id, scope=panel.SCOPED_REVIEW)
        is None
    )


def test_sqlite_writer_conflict_then_idempotent_retry(session, setup, tmp_path):
    value = plan(session, setup)
    path = tmp_path / "synthetic-concurrency.sqlite"
    raw = session.get_bind().raw_connection()
    try:
        with sqlite3.connect(path) as destination:
            raw.driver_connection.backup(destination)
    finally:
        raw.close()
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"timeout": 0.05})
    try:
        with Session(engine) as first, Session(engine) as second:
            assert apply(first, value)["records_appended"] == 5
            with pytest.raises(OperationalError, match="locked"):
                apply(second, value)
            second.rollback()
            first.commit()
            assert apply(second, value)["already_applied"] is True
            second.commit()
            assert second.scalar(select(func.count()).select_from(DecisionReview)) == 1
    finally:
        engine.dispose()


def test_unrelated_assignment_cannot_borrow_retained_receipt(session, setup):
    value = plan(session, setup)
    apply(session, value)
    session.commit()
    review = session.scalar(select(DecisionReview))
    review.candidate_result_id = setup.old_id
    session.commit()
    assert (
        wb.current_internal_decision_approval(session, setup.old_id, scope=panel.SCOPED_REVIEW)
        is None
    )
    assert (
        wb.current_internal_decision_approval(session, setup.target_id, scope=panel.SCOPED_REVIEW)
        is None
    )


@pytest.mark.parametrize("mode", ["dry_run", "unreviewed", "wrong_hash"])
def test_cli_requires_parent_hash_and_defaults_read_only(session, setup, monkeypatch, capsys, mode):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    namespace = runpy.run_path(str(scripts / "apply_decision_panel.py"))
    main = namespace["main"]
    engine = session.get_bind()
    session.rollback()
    main.__globals__["SessionLocal"] = lambda: Session(engine)
    original = wb.plan_decision_panel

    def checked_plan(db_session, directory):
        assert db_session.connection().exec_driver_sql("PRAGMA query_only").scalar() == 1
        return original(db_session, directory)

    main.__globals__["plan_decision_panel"] = checked_plan
    argv = ["apply_decision_panel.py", "--report-dir", str(setup.root)]
    if mode != "dry_run":
        argv.append("--apply")
    if mode == "wrong_hash":
        argv.extend(["--parent-reviewed-plan-sha256", "0" * 64])
    monkeypatch.setattr(sys, "argv", argv)
    if mode == "unreviewed":
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
    else:
        assert main() == (0 if mode == "dry_run" else 1)
        result = json.loads(capsys.readouterr().out)
        if mode == "dry_run":
            assert result["parent_review_required"] and not result["apply_performed"]
        else:
            assert result["status"] == "blocked"
    with Session(engine) as fresh:
        assert fresh.scalar(select(func.count()).select_from(DecisionReview)) == 0
        assert fresh.connection().exec_driver_sql("PRAGMA query_only").scalar() == 0


def packet_time(value):
    return datetime.fromisoformat(value.receipt["checked_at"])


def apply_at(session, value, at):
    return wb.apply_decision_panel(
        session, value, apply=True, parent_reviewed_plan_sha256=value.plan_sha256, now=at
    )


def test_apply_at_55_minutes_then_consume_at_two_hours(session, setup, monkeypatch):
    value = plan(session, setup)
    checked = packet_time(value)
    apply_at(session, value, checked + timedelta(minutes=55))
    session.commit()
    review = session.scalar(select(DecisionReview))
    assert value.receipt["version"] == "decision_writeback.v2"
    assert value.receipt["approval_max_age_seconds"] == 86400
    assert value.receipt["approval_lifetime_basis"] == "internal_engineering_cap"
    assert panel._utc(review.expiration_date) == checked + timedelta(hours=24)
    assert datetime.fromisoformat(value.receipt["report_expires_at"]) < panel._utc(
        review.expiration_date
    )
    calls = []
    original = panel.build_decision_packet

    def rebuilt(*args, **kwargs):
        calls.append(kwargs["now"])
        return original(*args, **kwargs)

    monkeypatch.setattr(panel, "build_decision_packet", rebuilt)
    for hours in (2, 3):
        at = checked + timedelta(hours=hours)
        approval = wb.current_internal_decision_approval(
            session, setup.target_id, scope=panel.SCOPED_REVIEW, now=at
        )
        assert approval is not None
        assert approval["expires_at"] == (checked + timedelta(hours=24)).isoformat()
        assert not approval["customer_eligible"] and not approval["rank_authorized"]
        assert not approval["human_review"] and not approval["aggregate_gate_updated"]
    assert calls == [checked + timedelta(hours=2), checked + timedelta(hours=3)]


def test_first_apply_at_65_minutes_rejected(session, setup):
    value = plan(session, setup)
    before = counts(session)
    session.rollback()
    with pytest.raises(wb.DecisionWritebackConflict, match="report_not_fresh"):
        apply_at(session, value, packet_time(value) + timedelta(minutes=65))
    session.rollback()
    assert counts(session) == before


def test_existing_apply_retry_keeps_strict_report_deadline(session, setup):
    value = plan(session, setup)
    apply(session, value)
    session.commit()
    with pytest.raises(wb.DecisionWritebackConflict, match="report_not_fresh"):
        apply_at(session, value, packet_time(value) + timedelta(hours=2))
    session.rollback()
    assert session.scalar(select(func.count()).select_from(DecisionReview)) == 1


def test_consumer_rejects_exact_24_hour_boundary(session, setup):
    value = plan(session, setup)
    apply(session, value)
    session.commit()
    assert (
        wb.current_internal_decision_approval(
            session,
            setup.target_id,
            scope=panel.SCOPED_REVIEW,
            now=packet_time(value) + timedelta(hours=24),
        )
        is None
    )


@pytest.mark.parametrize(
    "model,field", [(ProductSpecification, "valid_to"), (PriceSnapshot, "effective_to")]
)
def test_explicit_fact_or_price_validity_shortens_lifetime(session, setup, model, field):
    row = session.scalar(select(model))
    deadline = datetime.now(UTC) + timedelta(minutes=90)
    setattr(row, field, deadline)
    setup.extra_records.append((model, row.id))
    session.commit()
    setup.root = setup.make()
    value = plan(session, setup)
    checked = packet_time(value)
    assert datetime.fromisoformat(value.receipt["expires_at"]) == deadline
    assert value.receipt["explicit_validity_bounds"][0]["field"] == field
    apply_at(session, value, checked + timedelta(minutes=55))
    session.commit()
    assert panel._utc(session.scalar(select(DecisionReview)).expiration_date) == deadline
    assert (
        wb.current_internal_decision_approval(
            session,
            setup.target_id,
            scope=panel.SCOPED_REVIEW,
            now=checked + timedelta(minutes=70),
        )
        is not None
    )
    assert (
        wb.current_internal_decision_approval(
            session,
            setup.target_id,
            scope=panel.SCOPED_REVIEW,
            now=deadline,
        )
        is None
    )


def test_missing_audit_after_report_deadline_cannot_use_history(session, setup, monkeypatch):
    value = plan(session, setup)
    apply(session, value)
    session.commit()
    event = session.scalar(
        select(ModelReviewAuditEvent).where(ModelReviewAuditEvent.source == wb.SOURCE)
    )
    session.delete(event)
    session.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Must establish persisted writeback before reading historical report")

    monkeypatch.setattr(wb, "_validate_report", forbidden)
    assert (
        wb.current_internal_decision_approval(
            session,
            setup.target_id,
            scope=panel.SCOPED_REVIEW,
            now=packet_time(value) + timedelta(hours=2),
        )
        is None
    )


@pytest.mark.parametrize("damage", ["run", "finding", "late_event", "v1", "cap", "report_rewrite"])
def test_persistent_consumption_requires_original_complete_v2_receipt(session, setup, damage):
    value = plan(session, setup)
    apply(session, value)
    session.commit()
    event = session.scalar(
        select(ModelReviewAuditEvent).where(ModelReviewAuditEvent.source == wb.SOURCE)
    )
    review = session.scalar(select(DecisionReview))
    assignment_row = session.get(ModelReviewAssignment, event.assignment_id)
    if damage == "run":
        session.get(ModelReviewRun, assignment_row.precheck_run_id).summary_json = {}
    elif damage == "finding":
        session.get(ModelReviewFinding, assignment_row.precheck_finding_id).input_hash = "0" * 64
    elif damage == "late_event":
        event.timestamp = packet_time(value) + timedelta(minutes=65)
    elif damage in {"v1", "cap"}:
        receipt = json.loads(review.notes)
        receipt["version" if damage == "v1" else "approval_max_age_seconds"] = (
            "decision_writeback.v1" if damage == "v1" else 172800
        )
        review.notes = panel._json(receipt)
    else:
        summary = json.loads((setup.root / "summary.json").read_bytes())
        summary["local_comment"] = "Post-apply alteration must invalidate, even with rehashed files"
        write_json(setup.root / "summary.json", summary)
        rehash(setup.root)
    session.commit()
    assert (
        wb.current_internal_decision_approval(
            session,
            setup.target_id,
            scope=panel.SCOPED_REVIEW,
            now=packet_time(value) + timedelta(hours=2),
        )
        is None
    )


def test_report_ttl_must_be_strictly_less_than_65_minutes(session, setup):
    summary = json.loads((setup.root / "summary.json").read_bytes())
    summary["report_expires_at"] = (
        datetime.fromisoformat(summary["checked_at"]) + timedelta(minutes=65)
    ).isoformat()
    write_json(setup.root / "summary.json", summary)
    rehash(setup.root)
    with pytest.raises(wb.DecisionWritebackConflict, match="report_not_fresh"):
        plan(session, setup)


def test_normalized_fact_source_deadline_is_bound_and_revalidated(session, setup):
    fact = session.scalar(select(ProductSpecification))
    deadline = datetime.now(UTC) + timedelta(hours=3)
    fact.valid_to = deadline
    field = CanonicalFieldDefinition(
        code="synthetic.lifecycle",
        name="Synthetic lifetime test",
        domain="compute",
        data_type="numeric",
    )
    session.add(field)
    session.flush()
    rule = NormalizationRule(
        code="synthetic.lifecycle",
        version="v1",
        rule_type="field_mapping",
        canonical_field_id=field.id,
    )
    session.add(rule)
    session.flush()
    normalized = NormalizedSpecification(
        product_specification_id=fact.id,
        product_id=fact.product_id,
        sku_id=fact.sku_id,
        canonical_field_id=field.id,
        normalization_rule_id=rule.id,
        evidence_id=fact.evidence_id,
        scope_type="product",
        scope_identity="synthetic",
        value_qualifier="exact",
        numeric_value=2,
        raw_value="synthetic 2",
        source_value_hash="a" * 64,
    )
    session.add(normalized)
    session.flush()
    setup.extra_records.append((NormalizedSpecification, normalized.id))
    session.commit()
    setup.root = setup.make()
    value = plan(session, setup)
    assert value.receipt["expires_at"] == deadline.isoformat()
    assert value.receipt["explicit_validity_bounds"][0]["table"] == "product_specification"
    apply(session, value)
    session.commit()
    at = packet_time(value) + timedelta(hours=2)
    assert (
        wb.current_internal_decision_approval(
            session, setup.target_id, scope=panel.SCOPED_REVIEW, now=at
        )
        is not None
    )
    # The source fact is not directly listed in this synthetic panel manifest.
    # Extending even that deadline cannot silently extend an existing approval.
    fact.valid_to = deadline + timedelta(hours=1)
    session.commit()
    assert (
        wb.current_internal_decision_approval(
            session, setup.target_id, scope=panel.SCOPED_REVIEW, now=at
        )
        is None
    )
