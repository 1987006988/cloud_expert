"""Synthetic fixtures exercise planning only; none constitute real fact approval."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun, ReviewItem
from cloud_expert.model_review.repair_inventory import (
    TABLES,
    Inventory,
    _Planner,
    build_repair_inventory,
    inventory_from_sqlite,
    validate_repair_plan,
)
from cloud_expert.pricing import price_lifecycle


def synthetic_data() -> Inventory:
    data: Inventory = {name: {} for name in TABLES}
    data["model_review_run"][1] = {
        "id": 1,
        "run_code": "synthetic-precheck",
        "reviewer_model": "deterministic_evidence_precheck",
    }
    data["source_document"][1] = {"id": 1, "content_hash": "a" * 64}
    data["snapshot_record"][1] = {
        "id": 1,
        "source_document_id": 1,
        "content_hash": "a" * 64,
        "storage_path": "synthetic/raw.bin",
        "manifest_path": "synthetic/manifest.json",
    }
    data["evidence"][1] = {
        "id": 1,
        "source_document_id": 1,
        "snapshot_record_id": 1,
        "locator": "synthetic:table:1",
        "excerpt": "Synthetic specification only",
    }
    return data


def lifecycle_data() -> Inventory:
    """Synthetic linked envelope, not a live-validated receipt or price approval."""
    data = synthetic_data()
    digest, receipt_hash = "b" * 64, "c" * 64
    data["price_snapshot"] = {
        13: {"id": 13, "evidence_id": 1, "price_sku_id": 8},
        19: {"id": 19, "evidence_id": 1, "price_sku_id": 8},
    }
    data["model_review_run"][2] = {
        "id": 2,
        "reviewer_model": price_lifecycle.ACTOR,
        "policy_version": price_lifecycle.VERSION,
        "run_code": price_lifecycle.RUN_PREFIX + digest,
        "input_fingerprint": digest,
        "summary_json": {
            "schema_version": "price_replacement_receipt_v1",
            "receipt_sha256": receipt_hash,
            "plan": {"plan_sha256": digest},
        },
    }
    data["model_review_finding"][2] = {
        "id": 2,
        "run_id": 2,
        "subject_type": "price_snapshot",
        "subject_id": 13,
        "input_hash": digest,
        "evidence_ids": [1],
        "verdict": "superseded_by_verified_price",
        "reason_code": price_lifecycle.VERSION,
        "rationale": receipt_hash,
    }
    data["model_review_assignment"][2] = {
        "id": 2,
        "precheck_run_id": 2,
        "precheck_finding_id": 2,
        "target_type": "price_snapshot",
        "target_id": 13,
        "input_hash": digest,
        "evidence_ids": [1],
        "review_state": "superseded",
    }
    data["model_review_audit_event"][2] = {
        "id": 2,
        "assignment_id": 2,
        "event_code": f"{price_lifecycle.RUN_PREFIX}{digest}:13",
        "source": price_lifecycle.EVENT_SOURCE,
        "reason": price_lifecycle.VERSION,
        "model_id": None,
        "previous_status": None,
        "new_status": "superseded",
        "downstream_rebuild_required": True,
        "affected_records": [
            {
                "schema_version": "price_replacement_event_v1",
                "old_price_id": 13,
                "new_price_id": 19,
                "price_sku_id": 8,
                "receipt_sha256": receipt_hash,
                "plan_sha256": digest,
            }
        ],
    }
    return data


def test_dedicated_price_inventory_preserves_provenance_without_approving():
    data = lifecycle_data()
    before = copy.deepcopy(data)
    plan = _Planner(data).plan()
    (item,) = plan["items"]
    assert plan["planner_version"] == "review_repair_inventory_v2"
    assert item["root_cause"] == "price_lifecycle_requires_live_validation"
    assert item["proposed_action"] == "validate_price_lifecycle"
    assert item["flags"] == ["price_lifecycle_live_validation_required"]
    assert item["precheck_finding_id"] is None
    assert item["preconditions"]["requires_live_price_lifecycle_validation"] is True
    assert item["preconditions"]["requires_fresh_precheck"] is False
    provenance = item["price_lifecycle"]
    assert provenance["live_validation"] == "required_not_performed_by_inventory"
    assert provenance["approval_granted"] is False
    (envelope,) = provenance["envelopes"]
    assert envelope["run"] == data["model_review_run"][2]
    assert envelope["finding"] == data["model_review_finding"][2]
    assert envelope["audit_events"] == [data["model_review_audit_event"][2]]
    assert envelope["referenced_successor_rows"] == [data["price_snapshot"][19]]
    assert item["evidence_ids"] == [1]
    assert plan["approvals_granted"] == 0 and plan["database_writeback"] is False
    assert plan["summary"]["subjects"] == 1  # Do not enqueue unrelated price rows.
    assert data == before


@pytest.mark.parametrize(
    "mutation",
    [
        "no_audit",
        "wrong_namespace",
        "wrong_reviewer",
        "bad_receipt",
        "bad_plan",
        "bad_finding",
        "bad_assignment",
        "model_claim",
        "bad_event_hash",
        "bad_target",
        "no_successor",
        "wrong_sku",
        "duplicate_audit",
        "malformed_records",
    ],
)
def test_price_state_alone_cannot_hide_broken_lifecycle_provenance(mutation):
    data = lifecycle_data()
    run = data["model_review_run"][2]
    event = data["model_review_audit_event"][2]
    if mutation == "no_audit":
        data["model_review_audit_event"].clear()
    elif mutation == "wrong_namespace":
        event["source"] = "ordinary_model_review"
    elif mutation == "wrong_reviewer":
        run["reviewer_model"] = "synthetic_model"
    elif mutation == "bad_receipt":
        run["summary_json"] = ["not a receipt"]
    elif mutation == "bad_plan":
        run["summary_json"]["plan"] = []
    elif mutation == "bad_finding":
        data["model_review_finding"][2]["subject_id"] = 99
    elif mutation == "bad_assignment":
        data["model_review_assignment"][2]["input_hash"] = "e" * 64
    elif mutation == "model_claim":
        event["model_id"] = "synthetic_model"
    elif mutation == "bad_event_hash":
        event["affected_records"][0]["receipt_sha256"] = "e" * 64
    elif mutation == "bad_target":
        event["affected_records"][0]["old_price_id"] = 99
    elif mutation == "no_successor":
        del data["price_snapshot"][19]
    elif mutation == "wrong_sku":
        data["price_snapshot"][19]["price_sku_id"] = 999
    elif mutation == "duplicate_audit":
        data["model_review_audit_event"][3] = {**event, "id": 3}
    else:
        event["affected_records"] = {"new_price_id": 19}
    plan = _Planner(data).plan()
    (item,) = plan["items"]
    assert item["root_cause"] == "price_lifecycle_provenance_invalid"
    assert item["price_lifecycle"]["structural_issues"]
    assert item["proposed_action"] == "investigate_integrity"
    assert plan["approvals_granted"] == 0


def test_missing_price_and_unsupported_target_are_distinct():
    data = lifecycle_data()
    del data["price_snapshot"][13]
    (missing,) = _Planner(data).plan()["items"]
    assert missing["root_cause"] == "subject_missing"
    assert missing["price_lifecycle"]["envelopes"][0]["audit_events"]
    data["model_review_assignment"][2]["target_type"] = "unknown_table"
    (unknown,) = _Planner(data).plan()["items"]
    assert unknown["root_cause"] == "unsupported_subject_type"
    assert unknown["assignment_ids"] == [2]


def test_price_evidence_and_lifecycle_hash_drift_remain_visible():
    data = lifecycle_data()
    first = _Planner(data).plan()
    data["model_review_run"][2]["summary_json"]["unverified_note"] = "changed"
    second = _Planner(data).plan()
    assert first["plan_id"] != second["plan_id"]
    assert (
        first["items"][0]["preconditions"]["dependency_hash"]
        != second["items"][0]["preconditions"]["dependency_hash"]
    )
    del data["evidence"][1]
    assert _Planner(data).plan()["items"][0]["root_cause"] == "evidence_chain_incomplete"


def test_successor_price_evidence_is_included_and_must_exist():
    data = lifecycle_data()
    data["price_snapshot"][19]["evidence_id"] = 9
    (item,) = _Planner(data).plan()["items"]
    assert item["evidence_ids"] == [1, 9]
    assert item["root_cause"] == "evidence_chain_incomplete"


def add_subject(data: Inventory, kind: str, subject_id: int = 1, **values: object) -> None:
    data[kind][subject_id] = {"id": subject_id, **values}
    finding_id = len(data["model_review_finding"]) + 1
    data["model_review_finding"][finding_id] = {
        "id": finding_id,
        "run_id": 1,
        "subject_type": kind,
        "subject_id": subject_id,
        "input_hash": "b" * 64,
        "evidence_ids": [1],
        "verdict": "requires_source_verification",
        "reason_code": "synthetic",
    }


def add_field(data: Inventory, field: str, **values: object) -> None:
    add_subject(
        data,
        "review_item",
        status="open",
        field_code=field,
        parsed_field_candidate_id=1,
        evidence_id=1,
    )
    data["parsed_field_candidate"][1] = {
        "id": 1,
        "parsing_run_id": 1,
        "source_document_id": 1,
        "snapshot_record_id": 1,
        "target_table": "synthetic_specification",
        "target_identity": "synthetic:sku",
        "field_code": field,
        "evidence_id": 1,
        "review_status": "pending_review",
        "normalized_value": "8",
        **values,
    }


def test_latest_per_subject_preserves_targeted_and_full_runs() -> None:
    data = synthetic_data()
    add_subject(data, "review_item", 1, status="resolved")
    add_subject(data, "review_item", 2, status="open")
    data["model_review_run"][2] = {
        "id": 2,
        "run_code": "synthetic-targeted",
        "reviewer_model": "deterministic_evidence_precheck",
    }
    data["model_review_finding"][3] = {**data["model_review_finding"][1], "id": 3, "run_id": 2}
    data["model_review_run"][3] = {
        "id": 3,
        "run_code": "synthetic-model",
        "reviewer_model": "synthetic-model-not-precheck",
    }
    data["model_review_finding"][4] = {**data["model_review_finding"][1], "id": 4, "run_id": 3}
    data["model_review_assignment"][1] = {
        "id": 1,
        "precheck_run_id": 1,
        "precheck_finding_id": 1,
        "target_type": "review_item",
        "target_id": 1,
        "input_hash": "b" * 64,
        "evidence_ids": [1],
        "review_state": "superseded",
    }
    result = _Planner(data).plan()
    first, second = result["items"]
    assert first["precheck_run_code"] == "synthetic-targeted"
    assert second["precheck_run_code"] == "synthetic-precheck"
    assert first["assignment_ids"] == [1]
    assert first["root_cause"] == "historical_resolved"
    assert "historical_precheck_assignments_retained" in first["flags"]
    assert result["summary"]["subjects"] == 2


def test_successor_is_not_approval_and_must_match_snapshot_and_target_table() -> None:
    data = synthetic_data()
    add_field(data, "compute.memory_gib", normalized_value=None, review_status="rejected")
    old = data["parsed_field_candidate"][1]
    data["parsed_field_candidate"][2] = {**old, "id": 2, "target_table": "other"}
    data["parsed_field_candidate"][3] = {**old, "id": 3, "snapshot_record_id": 2}
    item = _Planner(data).plan()["items"][0]
    assert item["root_cause"] == "memory_column_non_numeric"
    assert item["replacement_candidate_ids"] == []
    data["parsed_field_candidate"][4] = {
        **old,
        "id": 4,
        "normalized_value": "8",
        "review_status": "machine_extracted",
    }
    plan = _Planner(data).plan()
    assert plan["items"][0]["root_cause"] == "parse_replacement_requires_validation"
    assert plan["items"][0]["replacement_candidate_ids"] == [4]
    assert plan["approvals_granted"] == 0
    assert plan["items"][0]["preconditions"]["requires_independent_review_for_fact_changes"]
    assert old["review_status"] == "rejected"


@pytest.mark.parametrize(
    ("field", "value", "root"),
    [
        ("compute.memory_gib", None, "memory_column_non_numeric"),
        ("compute.memory_gib", "No", "memory_column_non_numeric"),
        ("compute.memory_gib", "NaN", "memory_column_non_numeric"),
        ("compute.cpu_architecture", "processor model", "cpu_architecture_source_verification"),
        ("zone.name", "synthetic-zone", "zone_identity_availability_scope"),
        ("sla.availability_percentage", "99", "sla_request_storage_scope"),
        ("object_storage.redundancy_type", "synthetic", "object_storage_scope_qualifier"),
        ("compute.memory_gib", "8", "field_source_verification"),
    ],
)
def test_field_root_causes(field: str, value: str | None, root: str) -> None:
    data = synthetic_data()
    add_field(data, field, normalized_value=value)
    assert _Planner(data).plan()["items"][0]["root_cause"] == root


def test_rejected_parser_without_successor() -> None:
    data = synthetic_data()
    add_field(data, "gpu.model", review_status="rejected")
    assert _Planner(data).plan()["items"][0]["root_cause"] == "rejected_parser_output"


def test_missing_target_and_broken_chain_stay_accounted_for() -> None:
    data = synthetic_data()
    add_subject(data, "review_item", status="open")
    del data["review_item"][1]
    assert _Planner(data).plan()["items"][0]["root_cause"] == "subject_missing"
    data["review_item"][1] = {"id": 1, "status": "open"}
    data["snapshot_record"][1]["source_document_id"] = 2
    plan = _Planner(data).plan()
    assert plan["items"][0]["root_cause"] == "evidence_chain_incomplete"
    assert plan["evidence"][0]["chain_complete"] is False


def test_recorded_source_snapshot_hash_mismatch_blocks_but_excerpt_hash_may_differ() -> None:
    data = synthetic_data()
    add_field(data, "compute.memory_gib")
    data["evidence"][1]["content_hash"] = "e" * 64
    assert _Planner(data).plan()["evidence"][0]["chain_complete"] is True
    data["snapshot_record"][1]["content_hash"] = "f" * 64
    plan = _Planner(data).plan()
    assert plan["items"][0]["root_cause"] == "evidence_chain_incomplete"
    assert plan["evidence"][0]["raw_file_verification"].endswith("not_performed_by_inventory")


def test_existing_approval_is_preserved_but_not_reissued() -> None:
    data = synthetic_data()
    add_subject(data, "mapping_candidate", candidate_status="approved")
    data["model_review_assignment"][1] = {
        "id": 1,
        "precheck_run_id": 1,
        "precheck_finding_id": 1,
        "target_type": "mapping_candidate",
        "target_id": 1,
        "input_hash": "b" * 64,
        "evidence_ids": [1],
        "review_state": "model_approved_with_conditions",
    }
    before = copy.deepcopy(data)
    plan = _Planner(data).plan()
    assert "existing_approval_requires_scope_and_version_validation" in plan["items"][0]["flags"]
    assert plan["summary"]["assignment_state_counts"]["model_approved_with_conditions"] == 1
    assert plan["approvals_granted"] == 0
    assert data == before


@pytest.mark.parametrize(
    ("values", "root"),
    [
        ({"superseded_by_id": 9}, "historical_superseded"),
        ({"candidate_status": "superseded"}, "historical_superseded"),
        ({"candidate_status": "rejected"}, "mapping_rejected"),
        ({"blocking_reasons": ["missing_required_field"]}, "mapping_required_fields_missing"),
        ({"blocking_reasons": ["family_category_mismatch"]}, "mapping_category_mismatch"),
        ({"blocking_reasons": ["synthetic_block"]}, "mapping_hard_block"),
        ({"rule_set_id": 1}, "cross_market_research_only"),
        ({}, "mapping_source_verification"),
    ],
)
def test_mapping_dispositions(values: dict[str, object], root: str) -> None:
    data = synthetic_data()
    add_subject(data, "mapping_candidate", **values)
    data["mapping_rule_set"][1] = {"id": 1, "market_mode": "cross_market"}
    assert _Planner(data).plan()["items"][0]["root_cause"] == root


@pytest.mark.parametrize(
    ("status", "root"),
    [
        ("blocked", "decision_hard_block"),
        ("invalid_mapping", "decision_invalid_mapping"),
        ("incomplete_cost", "decision_cost_incomplete"),
        ("requires_review", "decision_evidence_incomplete"),
    ],
)
def test_decisions_never_approve_from_status_alone(status: str, root: str) -> None:
    data = synthetic_data()
    data["mapping_candidate"][1] = {"id": 1, "candidate_status": "candidate"}
    data["tco_result"][1] = {"id": 1, "completeness_status": "complete"}
    add_subject(
        data,
        "candidate_decision_result",
        mapping_candidate_id=1,
        decision_status=status,
        tco_result_id=1,
    )
    item = next(
        i
        for i in _Planner(data).plan()["items"]
        if i["subject_type"] == "candidate_decision_result"
    )
    assert item["root_cause"] == root


def test_stale_decision_package_and_mapping_are_not_active_parser_issues() -> None:
    data = synthetic_data()
    data["mapping_candidate"][1] = {"id": 1, "superseded_by_id": 2}
    add_subject(
        data,
        "candidate_decision_result",
        mapping_candidate_id=1,
        key_strength_conditions=[{"evidence_package_id": 4}],
    )
    result = _Planner(data).plan()
    assert result["items"][0]["root_cause"] == "decision_upstream_superseded"
    del data["mapping_candidate"][1]["superseded_by_id"]
    data["evidence_package"][4] = {"id": 4, "mapping_candidate_id": 1, "superseded_by_id": 5}
    assert _Planner(data).plan()["items"][0]["root_cause"] == "decision_package_superseded"


def test_comparability_scope_versions_and_evidence_are_preserved() -> None:
    data = synthetic_data()
    add_subject(
        data,
        "comparability_assessment",
        source_product_id=1,
        target_product_id=2,
        canonical_field_id=1,
        reason_code="scope_mismatch",
        review_status="pending_review",
    )
    data["normalized_specification"][1] = {
        "id": 1,
        "product_id": 1,
        "canonical_field_id": 1,
        "product_specification_id": 1,
        "scope_type": "service_tier",
        "evidence_id": 1,
    }
    data["normalized_specification"][2] = {
        **data["normalized_specification"][1],
        "id": 2,
        "scope_type": "product",
    }
    result = _Planner(data).plan()
    assert result["items"][0]["root_cause"] == "normalization_version_scope_conflict"
    assert result["items"][0]["evidence_ids"] == [1]
    assert len(data["normalized_specification"]) == 2


@pytest.mark.parametrize(
    "reason", ["missing_one_side", "missing_both_sides", "market_scope_differs"]
)
def test_comparability_limitations_are_not_product_weaknesses(reason: str) -> None:
    data = synthetic_data()
    add_subject(
        data, "comparability_assessment", reason_code=reason, review_status="pending_review"
    )
    plan = _Planner(data).plan()
    assert plan["items"][0]["proposed_action"] in {"collect_evidence", "retain_limitation"}
    assert plan["approvals_granted"] == 0


def test_unassigned_subject_and_assignment_conflict_are_visible() -> None:
    data = synthetic_data()
    data["review_item"][2] = {"id": 2, "status": "open"}
    add_subject(data, "review_item", status="open")
    data["model_review_assignment"][1] = {
        "id": 1,
        "precheck_run_id": 1,
        "precheck_finding_id": 1,
        "target_type": "review_item",
        "target_id": 1,
        "input_hash": "wrong",
        "evidence_ids": [1],
        "review_state": "pending_model_review",
    }
    result = _Planner(data).plan()
    assert result["summary"]["flag_counts"] == {
        "assignment_precheck_conflict": 1,
        "missing_deterministic_precheck": 1,
    }
    assert sum(result["summary"]["root_cause_counts"].values()) == result["summary"]["subjects"]


def test_manifest_is_deterministic_and_sensitive_to_evidence_and_queue_changes() -> None:
    data = synthetic_data()
    add_field(data, "compute.memory_gib")
    before = copy.deepcopy(data)
    plan = _Planner(data).plan()
    assert _Planner(data).plan() == plan
    assert data == before
    data["evidence"][1]["excerpt"] = "Synthetic changed source"
    changed = _Planner(data).plan()
    assert plan["plan_id"] != changed["plan_id"]
    assert (
        plan["items"][0]["preconditions"]["dependency_hash"]
        != changed["items"][0]["preconditions"]["dependency_hash"]
    )
    data["model_review_audit_event"][1] = {"id": 1, "reason": "synthetic_new_audit"}
    assert changed["plan_id"] != _Planner(data).plan()["plan_id"]


def test_session_validation_is_read_only_and_rejects_tampered_or_stale_plan(
    session: Session,
) -> None:
    item = ReviewItem(
        item_type="low_confidence_field",
        severity="medium",
        status="open",
        reason="Synthetic test only",
    )
    run = ModelReviewRun(
        run_code="synthetic",
        policy_version="test",
        reviewer_model="deterministic_evidence_precheck",
        input_fingerprint="a" * 64,
        reviewed_at=datetime.now(UTC),
        summary_json={},
    )
    session.add_all([item, run])
    with pytest.raises(ValueError, match="clean"):
        build_repair_inventory(session)
    session.flush()
    session.add(
        ModelReviewFinding(
            run_id=run.id,
            subject_type="review_item",
            subject_id=item.id,
            verdict="requires_source_verification",
            reason_code="synthetic",
            rationale="Synthetic",
            evidence_ids=[],
            input_hash="b" * 64,
        )
    )
    session.commit()
    plan = build_repair_inventory(session)
    validate_repair_plan(session, plan)
    assert not session.new and not session.dirty and not session.deleted
    tampered = copy.deepcopy(plan)
    tampered["approvals_granted"] = 1
    with pytest.raises(ValueError, match="stale or altered"):
        validate_repair_plan(session, tampered)
    item.reason = "Synthetic changed input"
    session.commit()
    with pytest.raises(ValueError, match="stale or altered"):
        validate_repair_plan(session, plan)


def test_sqlite_cli_reads_only_and_has_no_apply_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "synthetic.sqlite"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    before = database.read_bytes()
    original_connect = sqlite3.connect
    read_transactions: list[bool] = []

    def monitored_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden (id INTEGER)")
        connection.set_trace_callback(
            lambda statement: (
                read_transactions.append(connection.in_transaction)
                if statement.startswith("SELECT")
                else None
            )
        )
        return connection

    monkeypatch.setattr(sqlite3, "connect", monitored_connect)
    manifest = inventory_from_sqlite(database)
    assert read_transactions and all(read_transactions)
    assert manifest["dry_run"] and manifest["database_writeback"] is False
    assert database.read_bytes() == before
    script = Path(__file__).resolve().parents[2] / "scripts/plan_review_repairs.py"
    result = subprocess.run(
        [sys.executable, "-B", str(script), "--database", str(database), "--dry-run", "--summary"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["summary"]["subjects"] == 0
    result = subprocess.run(
        [sys.executable, "-B", str(script), "--apply"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert database.read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} == {"synthetic.sqlite"}
    with (
        sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection,
        pytest.raises(sqlite3.OperationalError, match="readonly"),
    ):
        connection.execute("CREATE TABLE forbidden (id INTEGER)")


def test_missing_sqlite_database_is_not_created(tmp_path: Path) -> None:
    from sqlalchemy.exc import OperationalError

    missing = tmp_path / "missing.sqlite"
    with pytest.raises(OperationalError):
        inventory_from_sqlite(missing)
    assert not missing.exists()


@pytest.mark.parametrize("precreate_empty", [False, True])
def test_cli_persists_full_report_even_in_summary_mode(
    tmp_path: Path, precreate_empty: bool
) -> None:
    database = tmp_path / "synthetic.sqlite"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ReviewItem(
                item_type="low_confidence_field",
                severity="medium",
                status="open",
                reason="Synthetic report persistence test",
            )
        )
        session.commit()
    engine.dispose()
    before = database.read_bytes()
    directory = tmp_path / "report"
    if precreate_empty:
        directory.mkdir()
    script = Path(__file__).resolve().parents[2] / "scripts/plan_review_repairs.py"
    command = [
        sys.executable,
        "-B",
        str(script),
        "--database",
        str(database),
        "--dry-run",
        "--summary",
        "--output-dir",
        str(directory),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    stdout = json.loads(result.stdout)
    payload = (directory / "manifest.json").read_bytes()
    manifest = json.loads(payload)
    metadata_bytes = (directory / "summary.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    assert manifest["items"][0]["subject_type"] == "review_item"
    assert "items" not in stdout
    assert metadata["summary"]["subjects"] == 1
    assert metadata["plan_id"] == manifest["plan_id"] == stdout["plan_id"]
    assert metadata["manifest_sha256"] == hashlib.sha256(payload).hexdigest()
    assert metadata["manifest_bytes"] == len(payload)
    assert metadata["source_snapshot_hash"] == manifest["source_snapshot_hash"]
    assert metadata["status"] == "complete" and metadata["database_writeback"] is False
    assert metadata["approvals_granted"] == 0 and metadata["gate_updated"] is False
    assert datetime.fromisoformat(metadata["generated_at"]).tzinfo is not None
    assert {p.name for p in directory.iterdir()} == {"manifest.json", "summary.json"}
    retry = subprocess.run(command, capture_output=True, text=True, check=False)
    assert retry.returncode == 2 and "not empty" in retry.stderr
    assert (directory / "manifest.json").read_bytes() == payload
    assert (directory / "summary.json").read_bytes() == metadata_bytes
    assert database.read_bytes() == before


def test_cli_refuses_nonempty_directory_without_report_files(tmp_path: Path) -> None:
    database = tmp_path / "synthetic.sqlite"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    directory = tmp_path / "report"
    directory.mkdir()
    sentinel = directory / "previous_failure.txt"
    sentinel.write_text("Synthetic preserved failure", encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts/plan_review_repairs.py"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(script),
            "--database",
            str(database),
            "--dry-run",
            "--output-dir",
            str(directory),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert {p.name for p in directory.iterdir()} == {sentinel.name}
    assert sentinel.read_text(encoding="utf-8") == "Synthetic preserved failure"
