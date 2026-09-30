"""Connectivity fixtures are synthetic and cannot approve a business review."""

import json
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from cloud_expert.model_review import registry
from cloud_expert.model_review.isolated_runtime import RuntimeIsolationError, isolated_config_args


@pytest.fixture
def probe(monkeypatch, tmp_path):
    state = SimpleNamespace(cleanup_failed=False, calls=[], returncode=0)
    state.events = [
        {"type": "thread.started", "thread_id": "synthetic-probe"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "id": "one", "text": "REVIEW_MODEL_READY"},
        },
        {"type": "turn.completed"},
    ]
    state.runtime = SimpleNamespace(
        cwd=tmp_path / "work",
        env={"CODEX_HOME": str(tmp_path / "home"), "PATH": "synthetic-path"},
        config_args=isolated_config_args(tmp_path / "home"),
    )

    @contextmanager
    def isolated():
        try:
            yield state.runtime
        finally:
            state.cleaned = True
            if state.cleanup_failed:
                raise RuntimeIsolationError("private_runtime_cleanup_failed")

    def execute(command, **kwargs):
        state.calls.append((command, kwargs))
        if hasattr(state, "failure"):
            raise state.failure
        stdout = b"\n".join(json.dumps(event).encode() for event in state.events)
        return subprocess.CompletedProcess(command, state.returncode, stdout, b"synthetic stderr")

    monkeypatch.setattr(registry, "isolated_review_runtime", isolated)
    monkeypatch.setattr(registry.shutil, "which", lambda _: "synthetic-codex")
    monkeypatch.setattr(registry.subprocess, "run", execute)
    return state


def test_probe_isolated_environment_and_exact_response(probe):
    result = registry.probe_codex_cli("gpt-6-astra")
    assert result["available"] is True
    assert result["model_identity_verified"] is False
    assert result["scope"] == "isolated_connectivity_only"
    command, kwargs = probe.calls[0]
    assert command[1:6] == ["exec", "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="max"']
    assert command[6:-1] == list(probe.runtime.config_args)
    assert command[-1] == "-" and kwargs["input"].startswith(b"Reply exactly")
    assert kwargs["cwd"] == probe.runtime.cwd
    assert kwargs["env"] == probe.runtime.env
    assert probe.cleaned
    assert "synthetic-path" not in json.dumps(result)


@pytest.mark.parametrize(
    "text", ["READY", "prefix REVIEW_MODEL_READY", "REVIEW_MODEL_READY suffix", ""]
)
def test_banner_or_substring_is_not_connectivity_proof(probe, text):
    probe.events[2]["item"]["text"] = text
    assert registry.probe_codex_cli("gpt-6-astra")["available"] is False


@pytest.mark.parametrize(
    "mutation", ["tool", "error", "missing_completion", "extra_turn", "nonzero"]
)
def test_failed_or_tool_using_probe_is_unavailable(probe, mutation):
    if mutation == "tool":
        probe.events[2]["item"]["type"] = "command_execution"
    elif mutation == "error":
        probe.events[2]["item"] = {"type": "error", "message": "synthetic-private-diagnostic"}
    elif mutation == "missing_completion":
        probe.events.pop()
    elif mutation == "extra_turn":
        probe.events.insert(2, {"type": "turn.started"})
    else:
        probe.returncode = 1
    result = registry.probe_codex_cli("gpt-6-astra")
    assert not result["available"] and probe.cleaned
    assert "synthetic-private-diagnostic" not in json.dumps(result)


@pytest.mark.parametrize(
    "failure", [OSError("synthetic-private"), subprocess.TimeoutExpired("synthetic", 1)]
)
def test_probe_execution_failure_is_sanitized(probe, failure):
    probe.failure = failure
    result = registry.probe_codex_cli("gpt-6-astra")
    assert result == {"available": False, "reason": type(failure).__name__}
    assert probe.cleaned


def test_probe_cleanup_failure_never_reports_available(probe):
    probe.cleanup_failed = True
    assert registry.probe_codex_cli("gpt-6-astra") == {
        "available": False,
        "reason": "RuntimeIsolationError",
    }


def test_absent_cli_never_initializes_credentials(monkeypatch):
    monkeypatch.setattr(registry.shutil, "which", lambda _: None)

    def forbidden():
        raise AssertionError("must not initialize authentication")

    monkeypatch.setattr(registry, "isolated_review_runtime", forbidden)
    assert not registry.probe_codex_cli("gpt-6-astra")["available"]
