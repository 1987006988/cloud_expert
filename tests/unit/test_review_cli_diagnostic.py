"""Synthetic-only regressions for the observed disabled-feature CLI diagnostic."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from cloud_expert.model_review import reproducibility as audit
from tests.unit.test_model_reproducibility import SyntheticBundle

NOTICE: dict[str, Any] = {
    "type": "item.completed",
    "item": {
        "id": "item_0",
        "type": "error",
        "message": (
            "Code Mode is unavailable because code-mode host is disabled. "
            "Code mode will fail closed; enable `features.code_mode_host` "
            "and install `codex-code-mode-host`."
        ),
    },
}


def synthetic_events() -> list[dict[str, Any]]:
    return [
        {"type": "thread.started", "thread_id": "synthetic-session"},
        deepcopy(NOTICE),
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "id": "item_1", "text": "SYNTHETIC result"},
        },
        {"type": "turn.completed", "usage": {"output_tokens": 2}},
    ]


@pytest.mark.parametrize("with_notice", [False, True])
def test_exact_startup_notice_returns_nonmutating_view(with_notice: bool) -> None:
    events = synthetic_events()
    if not with_notice:
        events.pop(1)
    original = deepcopy(events)
    validated = audit.validate_review_cli_events(events)
    assert events == original
    assert validated is not events
    assert [event["type"] for event in validated] == [
        "thread.started",
        "turn.started",
        "item.completed",
        "turn.completed",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "message",
        "whitespace",
        "outer_extra",
        "item_extra",
        "missing_id",
        "wrong_id",
        "wrong_type",
        "before_thread",
        "after_turn",
        "after_response",
        "after_completion",
        "duplicate",
        "id_reuse",
        "tool",
        "unknown_error",
        "extra_turn",
        "extra_thread",
        "extra_completion",
        "extra_response",
        "no_response",
        "truncated",
        "not_object",
    ],
)
def test_diagnostic_shape_order_cardinality_and_tools_fail_closed(mutation: str) -> None:
    events = synthetic_events()
    notice = events[1]
    if mutation == "message":
        notice["item"]["message"] = "Code Mode is unavailable."
    elif mutation == "whitespace":
        notice["item"]["message"] += " "
    elif mutation == "outer_extra":
        notice["extra"] = False
    elif mutation == "item_extra":
        notice["item"]["extra"] = False
    elif mutation == "missing_id":
        del notice["item"]["id"]
    elif mutation == "wrong_id":
        notice["item"]["id"] = "item_9"
    elif mutation == "wrong_type":
        notice["type"] = "item.started"
    elif mutation in {"before_thread", "after_turn", "after_response", "after_completion"}:
        events.pop(1)
        events.insert(
            {"before_thread": 0, "after_turn": 2, "after_response": 3, "after_completion": 4}[
                mutation
            ],
            notice,
        )
    elif mutation == "duplicate":
        events.insert(2, deepcopy(notice))
    elif mutation == "id_reuse":
        events[3]["item"]["id"] = "item_0"
    elif mutation in {"tool", "unknown_error"}:
        events[3]["item"]["type"] = "command_execution" if mutation == "tool" else "error"
    elif mutation in {"extra_turn", "extra_thread", "extra_completion", "extra_response"}:
        events.insert(
            3,
            deepcopy(
                events[
                    {
                        "extra_turn": 2,
                        "extra_thread": 0,
                        "extra_completion": 4,
                        "extra_response": 3,
                    }[mutation]
                ]
            ),
        )
    elif mutation == "no_response":
        events[3]["item"]["type"] = "reasoning"
    elif mutation == "truncated":
        events.pop()
    elif mutation == "not_object":
        events[3] = None  # type: ignore[assignment]
    with pytest.raises(audit.BundleError):
        audit.validate_review_cli_events(events)


@pytest.mark.parametrize(
    "metadata",
    [
        {"error": "synthetic failure"},
        {"fallback_used": True},
        {"previous_response_id": "synthetic-prior"},
        {"resumed_from": "synthetic-prior"},
        {"parent_thread_id": "synthetic-parent"},
        {"status": "failed"},
        {"actual_model_id": "weaker-model"},
        {"model_provider": "other"},
    ],
)
def test_notice_does_not_hide_nested_failure_metadata(metadata: dict[str, Any]) -> None:
    events = synthetic_events()
    events[3]["item"]["metadata"] = metadata
    with pytest.raises(audit.BundleError):
        audit.validate_review_cli_events(events)


def add_notice(bundle: Any) -> None:
    bundle.events["primary"][2]["item"]["id"] = "item_1"
    bundle.executions["primary"]["response_id"] = "item_1"
    bundle.events["primary"].insert(1, deepcopy(NOTICE))
    bundle.save_trace("primary")
    bundle.seal()


@pytest.mark.parametrize("native_identity", [False, True])
def test_bundle_accepts_exact_notice_and_preserves_raw_trace(
    tmp_path: Path, native_identity: bool
) -> None:
    bundle = SyntheticBundle(tmp_path)
    if native_identity:
        bundle.attach_runtime_identity("primary", persistent=True)
    add_notice(bundle)
    trace = tmp_path / bundle.manifest["stages"]["primary"]["trace"]["path"]
    original = trace.read_bytes()
    assert bundle.check()["status"] == "SYNTHETIC_VERIFIED"
    assert trace.read_bytes() == original
    assert sha256(original).hexdigest() == bundle.executions["primary"]["stdout_sha256"]


@pytest.mark.parametrize("mutation", ["response", "session", "model", "response_id"])
def test_bundle_still_binds_response_and_identity(tmp_path: Path, mutation: str) -> None:
    bundle = SyntheticBundle(tmp_path)
    add_notice(bundle)
    events = bundle.events["primary"]
    if mutation == "response":
        events[3]["item"]["text"] = "SYNTHETIC wrong response"
    elif mutation == "session":
        events[0]["thread_id"] = "synthetic-other-session"
    elif mutation == "model":
        del events[2]["model"]
    else:
        events[3]["item"]["id"] = "item_2"
    bundle.save_trace("primary")
    bundle.seal()
    assert bundle.check()["status"] == "BLOCKED"


@pytest.mark.parametrize("kind", ["error", "world_state"])
def test_native_runtime_has_no_unobserved_diagnostic_allowance(tmp_path: Path, kind: str) -> None:
    bundle = SyntheticBundle(tmp_path)
    bundle.attach_runtime_identity("primary", persistent=True)
    add_notice(bundle)
    event = {
        "type": "event_msg" if kind == "error" else kind,
        "timestamp": bundle.executions["primary"]["started_at"],
        "payload": {"type": "error", "message": NOTICE["item"]["message"]},
    }
    bundle.runtime_traces["primary"].insert(1, event)
    bundle.save_runtime("primary")
    bundle.seal()
    result = bundle.check()
    assert result["status"] == "BLOCKED"
    assert "runtime_unknown_event" in str(result)
