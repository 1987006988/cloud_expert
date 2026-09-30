import importlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from cloud_expert.model_review import internal_gate as gate
from cloud_expert.model_review.decision_panel import DecisionPacket


@pytest.fixture
def valid_inputs(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    payload: dict[str, Any] = {
        "data_classification": "official_public",
        "review_scope": gate.SCOPED_REVIEW,
        "subject": {"id": 7, "mapping_candidate_id": 3, "tco_result_id": 5},
        "scenario": {"market_mode": "domestic"},
        "evidence_package_ids": [11],
        "limitations": ["Synthetic fixture for testing only"],
    }
    approval: dict[str, Any] = {
        "input_fingerprint": "frozen",
        "review_scope": gate.SCOPED_REVIEW,
        "customer_eligible": False,
        "rank_authorized": False,
        "decision_review_id": 13,
        "evidence_ids": [17],
        "expires_at": "2026-10-01T00:00:00+00:00",
        "conditions": ["internal only"],
    }
    monkeypatch.setattr(
        gate,
        "build_decision_packet",
        lambda *a, **kw: DecisionPacket(json.dumps(payload), "{}", "frozen", "fixture"),
    )
    monkeypatch.setattr(gate, "current_internal_decision_approval", lambda *a, **kw: approval)
    return payload, approval


def test_internal_approval_never_grants_customer_rank_or_whole_week(valid_inputs: Any) -> None:
    with Session() as session:
        result = gate.internal_cost_readiness(session, 7)
    assert result["valid"]
    assert not result["customer_output_allowed"]
    assert not result["rank_authorized"]
    assert not result["production_authorized"]
    assert not result["week11_complete"]
    assert result["mapping_candidate_id"] == 3
    assert result["tco_result_id"] == 5
    assert result["review_conditions"] == ["internal only"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_fingerprint", "stale"),
        ("customer_eligible", True),
        ("review_scope", "sku_equivalence"),
        ("rank_authorized", True),
    ],
)
def test_changed_or_broader_approval_fails(valid_inputs: Any, field: str, value: Any) -> None:
    valid_inputs[1][field] = value
    with Session() as session:
        result = gate.internal_cost_readiness(session, 7)
    assert not result["valid"]
    assert result["allowed_operations"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_classification", "synthetic"),
        ("review_scope", "scenario_decision_only"),
    ],
)
def test_fixture_or_wrong_scope_cannot_approve_real_gate(
    valid_inputs: Any,
    field: str,
    value: str,
) -> None:
    valid_inputs[0][field] = value
    with Session() as session:
        assert not gate.internal_cost_readiness(session, 7)["valid"]


def test_no_real_panel_fails(valid_inputs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "current_internal_decision_approval", lambda *a, **kw: None)
    with Session() as session:
        result = gate.internal_cost_readiness(session, 7)
    assert result["blocking_items"] == ["current_independent_model_approval_required"]


def test_changed_input_fails(valid_inputs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def stale(*args: Any, **kwargs: Any) -> None:
        raise ValueError("decision_engine_or_dependencies_outdated")

    monkeypatch.setattr(gate, "build_decision_packet", stale)
    with Session() as session:
        result = gate.internal_cost_readiness(session, 7)
    assert not result["valid"]
    assert result["blocking_items"] == ["live_dependency_validation_failed"]


def test_invalid_subject_never_looks_up_data() -> None:
    with Session() as session:
        assert not gate.internal_cost_readiness(session, 0)["valid"]


def test_other_candidate_cannot_reuse_approval(valid_inputs: Any) -> None:
    with Session() as session:
        assert not gate.internal_cost_readiness(session, 8)["valid"]


@pytest.mark.parametrize(
    "week9,week10,reviewed",
    [
        ("NO-GO", "GO", True),
        ("GO", "NO-GO", True),
        ("GO", "GO", False),
        ("GO", "GO", True),
    ],
)
def test_internal_gate_never_bypasses_failed_dependency(
    monkeypatch: pytest.MonkeyPatch,
    week9: str,
    week10: str,
    reviewed: bool,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    script = importlib.import_module("check_week11_internal_gate")
    monkeypatch.setattr(script, "check_week09_gate", lambda: {"verdict": week9})
    monkeypatch.setattr(script, "check_week10_gate", lambda: {"verdict": week10})
    monkeypatch.setattr(script, "SessionLocal", MagicMock())
    monkeypatch.setattr(
        script,
        "internal_cost_readiness",
        lambda *a: {
            "valid": reviewed,
            "blocking_items": [] if reviewed else ["current_independent_model_approval_required"],
            "allowed_operations": ["view_reviewed_bounded_cost"] if reviewed else [],
        },
    )
    result = script.check_week11_internal_gate(7)
    expected = week9 == week10 == "GO" and reviewed
    assert (result["verdict"] == "GO") is expected
    assert result["internal_development_authorized"] is expected
    assert not result["customer_output_allowed"]
    assert not result["whole_week11_complete"]
    assert not result["subsequent_whole_week_gates_passed"]
    if not expected:
        assert result["allowed_operations"] == []
