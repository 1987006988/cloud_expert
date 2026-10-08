"""Auth-free synthetic CLI/native tests; no model calls or business DB access."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import yaml

from cloud_expert.model_review import decision_panel as panel
from cloud_expert.model_review import pilot, workflow
from cloud_expert.model_review import reproducibility as audit
from cloud_expert.model_review.approvals import PRODUCT_CATEGORY_CONDITIONS
from cloud_expert.model_review.isolated_runtime import RuntimeIsolationError, verify_local_artifact
from cloud_expert.model_review.schemas import AdversarialReview, PrimaryReview
from tests.unit.test_decision_panel import _install_synthetic_runtime
from tests.unit.test_review_native_isolation import synthetic_native_events


def _opinion(stage="primary"):
    if stage == "adversarial":
        return {
            "verdict": "agree",
            "identified_errors": [],
            "missing_conditions": [],
            "recommended_decision": "model_inconclusive",
            "confidence": 0.8,
            "evidence_references": [10],
            "reasoning_summary": "Synthetic review only.",
        }
    return {
        "decision": "model_inconclusive",
        "confidence": 0.8,
        "supported_by_evidence": False,
        "field_semantics_correct": False,
        "scope_correct": False,
        "market_scope_correct": False,
        "conditions": [],
        "blocking_reasons": ["Synthetic ambiguity"],
        "required_repairs": [],
        "evidence_references": [10],
        "reasoning_summary": "Synthetic review only.",
    }


@pytest.fixture
def harness(tmp_path, monkeypatch):
    state = _install_synthetic_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(pilot, "isolated_review_runtime", panel.isolated_review_runtime)
    monkeypatch.setattr(pilot, "protect_local_artifact", panel.protect_local_artifact)
    monkeypatch.setattr(pilot.shutil, "which", lambda _: "codex")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "forbidden-inherited-home"))
    monkeypatch.setenv("CODEX_THREAD_ID", "forbidden-inherited-thread")
    monkeypatch.setenv("PYTHONPATH", "forbidden-inherited-path")
    payload = {
        "target_type": "mapping_candidate",
        "target_id": 42,
        "precheck_verdict": "requires_dual_model_review",
        "precheck_run_code": "synthetic_mapping_isolation",
        "prompt_version": pilot.PROMPT_VERSION,
        "candidate": {
            "mapping_level": "product",
            "relationship_type": "same_service_class",
            "conditions": [sorted(PRODUCT_CATEGORY_CONDITIONS)[0]],
        },
        "evidence": [{"evidence_id": 10, "excerpt": "Synthetic public definition."}],
    }
    h = SimpleNamespace(
        state=state,
        payload=payload,
        root=tmp_path,
        calls=[],
        streams=[],
        mutation=None,
        raw=None,
        missing_native=False,
        duplicate_native=False,
        returncode=0,
        timeout=False,
        disagreement=False,
        opinions={},
    )

    def execute(command, **kwargs):
        h.calls.append((command, kwargs))
        prompt = kwargs["input"].decode("utf-8")
        schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_bytes())
        stage = "adversarial" if schema["title"] == "AdversarialReview" else "primary"
        if prompt.startswith("Arbitrate"):
            stage = "adjudication"
        opinion = h.opinions.get(stage, _opinion(stage))
        if h.disagreement and stage == "adversarial":
            opinion["verdict"] = "disagree"
        raw = h.raw if h.raw is not None else json.dumps(opinion).encode() + b"\r\n"
        response = raw.decode("utf-8")
        Path(command[command.index("-o") + 1]).write_bytes(raw)
        session_id, turn_id = str(uuid4()), str(uuid4())
        stdout_events = [
            {"type": "thread.started", "thread_id": session_id},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "id": "item_1", "text": response},
            },
            {"type": "turn.completed"},
        ]
        now = datetime.now(UTC)
        native, profile = synthetic_native_events(
            cwd=str(kwargs["cwd"]),
            session_id=session_id,
            turn_id=turn_id,
            prompt=prompt,
            response=response,
            started_at=now.isoformat(),
            completed_at=now.isoformat(),
        )
        monkeypatch.setattr(audit, "_CLEAN_NATIVE_PROFILE", profile)
        if h.mutation:
            h.mutation(native, stdout_events)
        native_raw = b"\r\n".join(json.dumps(e).encode() for e in native) + b"\r\n"
        if not h.missing_native:
            home = Path(kwargs["env"]["CODEX_HOME"])
            assert home in state.active_homes
            directory = home / "sessions" / now.strftime("%Y/%m/%d")
            directory.mkdir(parents=True)
            (directory / f"rollout-{now:%Y-%m-%dT%H-%M-%S}-{session_id}.jsonl").write_bytes(
                native_raw
            )
            if h.duplicate_native:
                (directory / f"rollout-duplicate-{session_id}.jsonl").write_bytes(native_raw)
        stdout = b"\r\n".join(json.dumps(e).encode() for e in stdout_events) + b"\r\n"
        stderr = f"session id: {session_id}\r\n".encode()
        h.streams.append(SimpleNamespace(raw=raw, stdout=stdout, stderr=stderr, native=native_raw))
        if h.timeout:
            raise subprocess.TimeoutExpired(command, 360, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(command, h.returncode, stdout, stderr)

    monkeypatch.setattr(pilot.subprocess, "run", execute)
    return h


def _run(harness, stage="primary", *, model=audit.MODEL_ID):
    schema = AdversarialReview if stage == "adversarial" else PrimaryReview
    return pilot._run_stage(stage, harness.payload, schema, harness.root, model)


@pytest.mark.parametrize("stage", ["primary", "adversarial", "adjudication"])
def test_stage_preserves_api_and_attests_isolated_exact_bytes(harness, stage, monkeypatch):
    original = panel._native_session_bytes
    capture_homes = []

    def capture(*args, codex_home=None):
        assert codex_home in harness.state.active_homes
        capture_homes.append(codex_home)
        return original(*args, codex_home=codex_home)

    monkeypatch.setattr(panel, "_native_session_bytes", capture)
    result, session_id = _run(harness, stage)
    assert result.model_dump(mode="json") == _opinion(stage)
    stage_dir = harness.root / stage
    receipt = json.loads((stage_dir / "execution.json").read_bytes())
    assert receipt["stage"] == stage
    if stage == "adjudication":
        receipt = json.loads((stage_dir / "audit.execution.json").read_bytes())
    metadata = audit.ExecutionMetadata.model_validate(receipt)
    assert metadata.stage == ("arbitration" if stage == "adjudication" else stage)
    assert metadata.session_id == session_id
    assert metadata.actual_model_id == audit.MODEL_ID
    assert metadata.model_provider == "openai"
    assert metadata.model_version == "alias_unresolved"
    audit._argv(metadata, has_runtime_identity=True, require_isolation=True)
    command, kwargs = harness.calls[0]
    runtime = harness.state.runtimes[0]
    assert capture_homes == [runtime.home]
    assert kwargs["cwd"] == runtime.cwd != stage_dir
    assert kwargs["env"] == dict(runtime.env)
    assert not {"CODEX_THREAD_ID", "PYTHONPATH"} & kwargs["env"].keys()
    assert "--ephemeral" not in command and "--json" in command
    assert 'model_reasoning_effort="max"' in command
    assert command[-1] == "-" and not any("INPUT_JSON" in arg for arg in command)
    assert isinstance(kwargs["input"], bytes) and kwargs["timeout"] == 360
    assert "encoding" not in kwargs and "text" not in kwargs
    streams = harness.streams[0]
    for filename, raw in (
        ("stdout.jsonl", streams.stdout),
        ("stderr.txt", streams.stderr),
        ("response.raw.json", streams.raw),
        ("runtime.native.jsonl", streams.native),
    ):
        assert (stage_dir / filename).read_bytes() == raw
    assert json.loads((stage_dir / "response.json").read_bytes()) == _opinion(stage)
    assert metadata.response_sha256 == hashlib.sha256(streams.raw).hexdigest()
    privacy = json.loads((stage_dir / "privacy.json").read_bytes())
    assert privacy["identity_verified"] is privacy["isolated_home_used"] is True
    assert privacy["local_only"] is True and privacy["transmit_to_model"] is False
    assert privacy["finding_codes"] == []
    refs = audit.StageArtifacts.model_validate(
        json.loads((stage_dir / "artifacts.json").read_bytes())
    )
    assert refs.runtime_identity is not None
    if stage == "adjudication":
        assert refs.execution.path == "adjudication/audit.execution.json"
    assert refs.runtime_identity.trace.sha256 == hashlib.sha256(streams.native).hexdigest()
    assert stage_dir in harness.state.protected
    assert stage_dir / "runtime.native.jsonl" in harness.state.protected
    verify_local_artifact(stage_dir / "runtime.native.jsonl")


def test_stages_use_independent_runtime_and_no_prior_opinion(harness, monkeypatch):
    monkeypatch.setattr(pilot, "mapping_review_input", lambda *_: harness.payload)
    summary = pilot.run_mapping_pilot(None, "synthetic", 42, harness.root, audit.MODEL_ID)
    assert summary["status"] == "completed"
    assert summary["primary_session_id"] != summary["adversarial_session_id"]
    assert summary["customer_eligible"] is summary["database_writeback"] is False
    assert len({runtime.home for runtime in harness.state.runtimes}) == 2
    assert len({runtime.cwd for runtime in harness.state.runtimes}) == 2
    for _, kwargs in harness.calls:
        assert b"primary_opinion" not in kwargs["input"]
        assert b"adversarial_opinion" not in kwargs["input"]


def test_arbitration_keeps_legacy_report_name_and_separate_native_session(harness, monkeypatch):
    harness.disagreement = True
    monkeypatch.setattr(pilot, "mapping_review_input", lambda *_: harness.payload)
    summary = pilot.run_mapping_pilot(None, "synthetic", 42, harness.root, audit.MODEL_ID)
    assert summary["status"] == "completed"
    assert (
        len(
            {summary[f"{stage}_session_id"] for stage in ("primary", "adversarial", "adjudication")}
        )
        == 3
    )
    assert len({runtime.home for runtime in harness.state.runtimes}) == 3
    root = Path(summary["report_dir"])
    assert (
        json.loads((root / "adjudication/execution.json").read_bytes())["stage"] == "adjudication"
    )
    assert (
        json.loads((root / "adjudication/audit.execution.json").read_bytes())["stage"]
        == "arbitration"
    )
    prompt = harness.calls[2][1]["input"].decode()
    payload = json.loads(prompt.split("\nINPUT_JSON:\n", 1)[1])
    assert payload["primary_opinion"] == _opinion()
    assert payload["adversarial_opinion"] == {**_opinion("adversarial"), "verdict": "disagree"}


@pytest.mark.parametrize("stage", ["primary", "adversarial"])
@pytest.mark.parametrize("key", ["primary_opinion", "adversarial_opinion", "prior_messages"])
def test_independent_stage_rejects_prior_context_before_launch(harness, stage, key):
    harness.payload["candidate"][key] = {"text": "synthetic prior opinion"}
    with pytest.raises(RuntimeError, match="mapping_stage_preflight_failed"):
        _run(harness, stage)
    assert harness.calls == [] and harness.state.runtimes == []


@pytest.mark.parametrize("model", ["synthetic-model", "gpt-6-sol", "", "gpt-6-astra --resume"])
def test_other_model_cannot_run_or_copy_auth(harness, model):
    with pytest.raises(RuntimeError, match="mapping_stage_preflight_failed"):
        _run(harness, model=model)
    assert harness.calls == [] and harness.state.runtimes == []


@pytest.mark.parametrize("damage", ["transfer", "model", "classes", "registry", "alias_policy"])
def test_policy_rechecked_without_an_availability_probe(harness, monkeypatch, damage):
    config = harness.root / "config"
    config.mkdir()
    for name in ("model_registry.yaml", "review_authorization.yaml", "reproducibility_policy.yaml"):
        (config / name).write_bytes((pilot.CONFIG / name).read_bytes())
    name = "review_authorization.yaml"
    value = yaml.safe_load((config / name).read_bytes())
    if damage == "transfer":
        value["external_data_transfer_approved"] = False
    elif damage == "model":
        value["approved_model"] = "gpt-6-sol"
    elif damage == "classes":
        value["approved_payload_classes"].remove("mapping_candidates")
    elif damage == "registry":
        name = "model_registry.yaml"
        value = yaml.safe_load((config / name).read_bytes())
        for model in value["models"]:
            model["approved_for_review"] = False
    else:
        name, value = "reproducibility_policy.yaml", {}
    (config / name).write_text(yaml.safe_dump(value), encoding="utf-8")
    monkeypatch.setattr(pilot, "CONFIG", config)
    with pytest.raises(RuntimeError, match="mapping_stage_preflight_failed"):
        _run(harness)
    assert harness.calls == [] and harness.state.runtimes == []


@pytest.mark.parametrize("field", ["customer_id", "personal_discounts", "account_name"])
def test_private_input_never_reaches_subprocess(harness, field):
    harness.payload["candidate"][field] = "synthetic private value"
    with pytest.raises(RuntimeError, match="mapping_stage_preflight_failed"):
        _run(harness)
    assert harness.calls == []


def _mutate(native, stdout, kind):
    meta = next(e["payload"] for e in native if e["type"] == "session_meta")
    context = next(e["payload"] for e in native if e["type"] == "turn_context")
    if kind == "model":
        context["model"] = "gpt-6-sol"
    elif kind == "provider":
        meta["model_provider"] = "another-provider"
    elif kind == "effort":
        context["effort"] = "high"
    elif kind == "thread":
        meta["id"] = str(uuid4())
    elif kind == "tool":
        stdout[2]["item"]["type"] = "command_execution"
    elif kind == "fallback":
        stdout[1]["fallback_used"] = True
    elif kind == "stdout_response":
        stdout[2]["item"]["text"] = "{}"
    elif kind == "duplicate_turn":
        stdout.insert(2, {"type": "turn.started"})
    elif kind == "private_native":
        meta["customer_id"] = "synthetic-customer"
    elif kind == "auth_secret":
        meta["creator_account_id"] = "sk-" + "x" * 20
    elif kind == "native_tool":
        native.insert(-1, {"type": "response_item", "payload": {"type": "function_call"}})
    elif kind == "world_state":
        world = next(e["payload"] for e in native if e["type"] == "world_state")
        world["state"]["host_skills"] = {
            "body": "Inherited synthetic catalog",
            "includeInstructions": True,
        }
    elif kind == "turn":
        context["turn_id"] = str(uuid4())
    elif kind in {"native_response", "prompt"}:
        role = "assistant" if kind == "native_response" else "user"
        item = next(
            e["payload"]
            for e in reversed(native)
            if e["type"] == "response_item" and e["payload"].get("role") == role
        )
        item["content"][0]["text"] += " "
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    [
        "model",
        "provider",
        "effort",
        "thread",
        "tool",
        "fallback",
        "stdout_response",
        "duplicate_turn",
        "private_native",
        "auth_secret",
        "native_tool",
        "native_response",
        "prompt",
        "world_state",
        "turn",
    ],
)
def test_invalid_runtime_identity_or_content_fails_closed(harness, kind):
    harness.mutation = lambda native, stdout: _mutate(native, stdout, kind)
    with pytest.raises(RuntimeError, match="mapping_stage_failed_validation_or_execution"):
        _run(harness)
    stage = harness.root / "primary"
    receipt = json.loads((stage / "execution.json").read_bytes())
    assert receipt["status"] == "failed"
    assert not (stage / "artifacts.json").exists()
    assert (stage / "response.raw.json").read_bytes() == harness.streams[0].raw
    assert "synthetic-customer" not in (stage / "execution.json").read_text()
    assert "sk-" not in (stage / "execution.json").read_text()


@pytest.mark.parametrize("kind", ["missing_native", "duplicate_native"])
def test_cli_and_stderr_identity_alone_are_never_enough(harness, kind):
    setattr(harness, kind, True)
    with pytest.raises(RuntimeError, match="mapping_stage_failed_validation_or_execution"):
        _run(harness)
    receipt = json.loads((harness.root / "primary/execution.json").read_bytes())
    assert receipt["reason_code"] == "runtime_session_missing_or_ambiguous"


@pytest.mark.parametrize("field", ["fresh_home", "sanitized_environment", "private_permissions"])
def test_attestation_failure_never_enables_metadata_exemption(harness, monkeypatch, field):
    original = pilot.isolated_review_runtime

    @contextmanager
    def invalid():
        with original() as runtime:
            yield replace(runtime, attestation={**runtime.attestation, field: False})

    monkeypatch.setattr(pilot, "isolated_review_runtime", invalid)
    sensitivity = Mock(wraps=panel._runtime_sensitivity)
    monkeypatch.setattr(panel, "_runtime_sensitivity", sensitivity)
    with pytest.raises(RuntimeError, match="mapping_stage_failed_validation_or_execution"):
        _run(harness)
    assert not any(
        call.kwargs.get("verified_isolated_native") for call in sensitivity.call_args_list
    )
    privacy = json.loads((harness.root / "primary/privacy.json").read_bytes())
    assert privacy["identity_verified"] is False


def test_cleanup_failure_cannot_leave_a_completed_receipt(harness, monkeypatch):
    original = pilot.isolated_review_runtime

    @contextmanager
    def cleanup_failure():
        with original() as runtime:
            yield runtime
        raise RuntimeIsolationError("synthetic_cleanup_failure")

    monkeypatch.setattr(pilot, "isolated_review_runtime", cleanup_failure)
    with pytest.raises(RuntimeError, match="mapping_stage_failed_validation_or_execution"):
        _run(harness)
    stage = harness.root / "primary"
    receipt = json.loads((stage / "execution.json").read_bytes())
    assert receipt["status"] == "failed"
    assert receipt["reason_code"] == "synthetic_cleanup_failure"
    assert not (stage / "artifacts.json").exists()
    assert (stage / "response.raw.json").read_bytes() == harness.streams[0].raw


def test_native_permission_failure_never_enables_metadata_exemption(harness, monkeypatch):
    def reject_native(path):
        assert path.name == "runtime.native.jsonl"
        raise RuntimeIsolationError("synthetic_permissions_invalid")

    monkeypatch.setattr(panel, "protect_local_artifact", reject_native)
    sensitivity = Mock(wraps=panel._runtime_sensitivity)
    monkeypatch.setattr(panel, "_runtime_sensitivity", sensitivity)
    with pytest.raises(RuntimeError, match="mapping_stage_failed_validation_or_execution"):
        _run(harness)
    assert not any(
        call.kwargs.get("verified_isolated_native") for call in sensitivity.call_args_list
    )
    receipt = json.loads((harness.root / "primary/execution.json").read_bytes())
    assert receipt["reason_code"] == "synthetic_permissions_invalid"
    assert not (harness.root / "primary/artifacts.json").exists()


@pytest.mark.parametrize("failure", ["timeout", "nonzero", "schema", "evidence", "duplicate_json"])
def test_failed_output_is_preserved_without_success_artifacts(harness, failure):
    if failure == "timeout":
        harness.timeout = True
    elif failure == "nonzero":
        harness.returncode = 1
    elif failure == "schema":
        harness.raw = b'{"unknown":"synthetic"}\r\n'
    elif failure == "evidence":
        harness.raw = json.dumps({**_opinion(), "evidence_references": [999]}).encode()
    else:
        harness.raw = (
            json.dumps(_opinion())
            .replace('"confidence": 0.8', '"confidence": 0.8, "confidence": 0.9')
            .encode()
        )
    with pytest.raises(RuntimeError, match="mapping_stage_failed_validation_or_execution"):
        _run(harness)
    stage = harness.root / "primary"
    assert json.loads((stage / "execution.json").read_bytes())["status"] == "failed"
    assert (stage / "response.raw.json").read_bytes() == harness.streams[0].raw
    assert (stage / "stdout.jsonl").read_bytes() == harness.streams[0].stdout
    assert not (stage / "artifacts.json").exists()


def _report(harness, monkeypatch):
    monkeypatch.setattr(pilot, "mapping_review_input", lambda *_: harness.payload)
    summary = pilot.run_mapping_pilot(None, "synthetic", 42, harness.root, audit.MODEL_ID)
    assert summary["status"] == "completed", summary
    return Path(summary["report_dir"])


def _rewrite(path, value):
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    path.write_bytes(panel._json(value).encode())


def _reseal(root):
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        artifact_path = directory / "artifacts.json"
        refs = json.loads(artifact_path.read_bytes())

        def update(value):
            if isinstance(value, dict):
                if set(value) == {"path", "sha256"}:
                    target = root / value["path"]
                    if target.is_file() and target.is_relative_to(root):
                        value["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
                else:
                    for item in value.values():
                        update(item)

        update(refs)
        _rewrite(artifact_path, refs)
    manifest = json.loads((root / "manifest.json").read_bytes())
    manifest["artifact_sha256"] = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    manifest["artifact_set_sha256"] = panel._hash(manifest["artifact_sha256"])
    _rewrite(root / "manifest.json", manifest)


@pytest.mark.parametrize("arbitration", [False, True])
def test_real_artifacts_reverify_without_models_or_auth(harness, monkeypatch, arbitration):
    harness.disagreement = arbitration
    root = _report(harness, monkeypatch)
    calls = len(harness.calls)
    receipt, reader = pilot.validate_mapping_pilot_artifacts(root, approved_model=audit.MODEL_ID)
    reader.unchanged()
    assert receipt["version"] == "week14.mapping.v2"
    assert (
        receipt["manifest_sha256"]
        == hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    )
    assert len(harness.calls) == calls


@pytest.mark.parametrize(
    "damage",
    [
        "raw",
        "parsed",
        "prompt",
        "template",
        "schema",
        "native",
        "stdout",
        "isolation",
        "argv",
        "privacy",
        "scope",
        "v1",
        "path_escape",
        "cross_stage_path",
        "missing",
        "extra",
        "session",
    ],
)
def test_resealed_runtime_artifact_tampering_cannot_pass(harness, monkeypatch, damage):
    root = _report(harness, monkeypatch)
    stage = root / "primary"
    path = stage / "execution.json"
    if damage in {"raw", "parsed"}:
        path = stage / ("response.raw.json" if damage == "raw" else "response.json")
        value = json.loads(path.read_bytes())
        value["reasoning_summary"] = "Changed synthetic opinion"
    elif damage in {"prompt", "template", "native", "stdout"}:
        filename = {
            "prompt": "prompt.txt",
            "template": "template.txt",
            "native": "runtime.native.jsonl",
            "stdout": "stdout.jsonl",
        }[damage]
        path = stage / filename
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
        path.write_bytes(path.read_bytes() + b" ")
        _reseal(root)
        with pytest.raises((ValueError, RuntimeError, OSError)):
            pilot.validate_mapping_pilot_artifacts(root, approved_model=audit.MODEL_ID)
        return
    elif damage == "schema":
        path, value = stage / "schema.json", {"type": "object"}
    elif damage in {"isolation", "argv", "session"}:
        value = json.loads(path.read_bytes())
        if damage == "isolation":
            value["runtime_isolation"]["fresh_home"] = False
        elif damage == "argv":
            value["argv"].insert(-1, "--ephemeral")
            value["argv_sha256"] = panel._hash(value["argv"])
        else:
            value["session_id"] = json.loads((root / "adversarial/execution.json").read_bytes())[
                "session_id"
            ]
    elif damage == "privacy":
        path = stage / "privacy.json"
        value = json.loads(path.read_bytes())
        value["identity_verified"] = False
    elif damage in {"scope", "v1"}:
        path = root / "summary.json"
        value = json.loads(path.read_bytes())
        value["customer_eligible" if damage == "scope" else "prompt_version"] = (
            True if damage == "scope" else "week14.mapping.v1"
        )
    elif damage in {"path_escape", "cross_stage_path"}:
        path = stage / "artifacts.json"
        value = json.loads(path.read_bytes())
        value["response"]["path"] = (
            "../outside.json" if damage == "path_escape" else "adversarial/response.raw.json"
        )
    elif damage == "missing":
        path = stage / "runtime.native.jsonl"
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
        path.unlink()
        _reseal(root)
        with pytest.raises((ValueError, RuntimeError, OSError)):
            pilot.validate_mapping_pilot_artifacts(root, approved_model=audit.MODEL_ID)
        return
    else:
        path, value = root / "unexpected.json", {}
        path.touch()
    _rewrite(path, value)
    _reseal(root)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        pilot.validate_mapping_pilot_artifacts(root, approved_model=audit.MODEL_ID)


def test_writeback_permissions_rechecked_before_privacy_exemption(harness, monkeypatch):
    root = _report(harness, monkeypatch)
    monkeypatch.setattr(
        pilot,
        "verify_local_artifact",
        Mock(side_effect=RuntimeIsolationError("permissions_invalid")),
    )
    scan = Mock(wraps=panel._runtime_sensitivity)
    monkeypatch.setattr(panel, "_runtime_sensitivity", scan)
    with pytest.raises(RuntimeIsolationError, match="permissions_invalid"):
        pilot.validate_mapping_pilot_artifacts(root, approved_model=audit.MODEL_ID)
    assert not any(call.kwargs.get("verified_isolated_native") for call in scan.call_args_list)


def test_mapping_conditions_are_exact_candidate_text_and_unknowns_survive_nonapproval(harness):
    canonical = harness.payload["candidate"]["conditions"][0]
    allowed = PrimaryReview.model_validate(
        {**_opinion(), "decision": "model_approved_with_conditions", "conditions": [canonical]}
    )
    pilot._validate_conditions("primary", harness.payload, allowed)
    for unknown in (
        canonical + " ",
        "Check region suitability later",
        sorted(PRODUCT_CATEGORY_CONDITIONS)[1],
    ):
        negative = PrimaryReview.model_validate({**_opinion(), "conditions": [unknown, unknown]})
        pilot._validate_conditions("primary", harness.payload, negative)
        assert negative.conditions == [unknown, unknown]
        with pytest.raises(ValueError, match="unenforceable_mapping_conditions"):
            pilot._validate_conditions(
                "primary",
                harness.payload,
                negative.model_copy(update={"decision": pilot.Decision.CONDITIONAL}),
            )


def test_arbitration_cannot_drop_reword_or_deduplicate_original_conditions(harness):
    text = "Unknown synthetic requirement"
    payload = {
        **harness.payload,
        "primary_opinion": {"conditions": [text, text]},
        "adversarial_opinion": {"missing_conditions": ["Another requirement"]},
    }
    for conditions in ([], [text], [text.upper(), text, "Another requirement"], [text, text]):
        opinion = PrimaryReview.model_validate({**_opinion(), "conditions": conditions})
        with pytest.raises(ValueError, match="arbitration_conditions_not_preserved"):
            pilot._validate_conditions("adjudication", payload, opinion)
    preserved = PrimaryReview.model_validate(
        {**_opinion(), "conditions": [text, text, "Another requirement"]}
    )
    pilot._validate_conditions("adjudication", payload, preserved)


@pytest.mark.parametrize("tamper", [False, True, "legacy"])
def test_fresh_workflow_apply_requires_verified_runtime_before_any_mutation(
    harness, monkeypatch, tamper
):
    root = _report(harness, monkeypatch)
    if tamper is True:
        path = root / "primary/response.raw.json"
        _rewrite(path, {**_opinion(), "reasoning_summary": "Tampered"})
        _reseal(root)
    elif tamper == "legacy":
        manifest = root / "manifest.json"
        manifest.unlink()
    run = SimpleNamespace(id=1)
    assignment = SimpleNamespace(id=2, review_state="pending_model_review", evidence_ids=[10])
    session = Mock(new=set(), dirty=set(), deleted=set())
    session.scalar.side_effect = [run, assignment, None]
    monkeypatch.setattr(workflow, "mapping_review_input", lambda *_: harness.payload)
    if tamper:
        with pytest.raises((ValueError, OSError, RuntimeError)):
            workflow.apply_mapping_pilot_result(session, root, approved_model=audit.MODEL_ID)
        assert assignment.review_state == "pending_model_review"
        session.add.assert_not_called()
        session.commit.assert_not_called()
    else:
        result = workflow.apply_mapping_pilot_result(session, root, approved_model=audit.MODEL_ID)
        assert result["status"] == "applied_nonapproval"
        event = session.add.call_args.args[0]
        assert event.affected_records[0]["runtime_attestation"]["version"] == pilot.PROMPT_VERSION


def test_real_conditional_approval_artifacts_apply_only_to_category_scope(harness, monkeypatch):
    conditions = harness.payload["candidate"]["conditions"]
    harness.opinions["primary"] = {
        **_opinion(),
        "decision": "model_approved_with_conditions",
        "conditions": conditions,
        "supported_by_evidence": True,
        "field_semantics_correct": True,
        "scope_correct": True,
        "market_scope_correct": True,
        "blocking_reasons": [],
    }
    harness.opinions["adversarial"] = {
        **_opinion("adversarial"),
        "recommended_decision": "model_approved_with_conditions",
    }
    root = _report(harness, monkeypatch)
    candidate = SimpleNamespace(
        mapping_level="product",
        relationship_type="same_service_class",
        conditions=conditions,
        candidate_status="candidate",
    )
    assignment = SimpleNamespace(id=2, review_state="pending_model_review", evidence_ids=[10])
    session = Mock(new=set(), dirty=set(), deleted=set())
    session.get.return_value = candidate
    session.scalar.side_effect = [SimpleNamespace(id=1), assignment, None]
    monkeypatch.setattr(workflow, "mapping_review_input", lambda *_: harness.payload)
    monkeypatch.setattr(workflow, "mapping_subject_hash", lambda _: "synthetic-subject-hash")
    result = workflow.apply_mapping_pilot_result(session, root, approved_model=audit.MODEL_ID)
    assert result["status"] == "applied_scoped_approval"
    assert result["customer_eligible"] is False
    event = session.add.call_args.args[0]
    record = event.affected_records[0]
    assert record["approved_scope"] == "product_category_only"
    assert record["review_conditions"] == conditions
    assert record["runtime_attestation"]["version"] == pilot.PROMPT_VERSION
    assert candidate.candidate_status == "approved"
    assert assignment.review_state == "model_approved_with_conditions"


def test_already_applied_legacy_history_is_not_rewritten_or_reapproved(harness, monkeypatch):
    root = _report(harness, monkeypatch)
    payload = json.loads((root / "input.json").read_bytes())
    summary = json.loads((root / "summary.json").read_bytes())
    payload["prompt_version"] = summary["prompt_version"] = "week14.mapping.v1"
    summary["input_hash"] = pilot._fingerprint({"payload": payload, "model_id": audit.MODEL_ID})
    _rewrite(root / "input.json", payload)
    _rewrite(root / "summary.json", summary)
    (root / "manifest.json").unlink()
    assignment = SimpleNamespace(id=2, review_state="model_inconclusive", evidence_ids=[10])
    session = Mock(new=set(), dirty=set(), deleted=set())
    session.scalar.side_effect = [SimpleNamespace(id=1), assignment, SimpleNamespace(id=3)]
    verify = Mock(side_effect=AssertionError("Legacy history is not a new approval"))
    monkeypatch.setattr(workflow, "validate_mapping_pilot_artifacts", verify)
    result = workflow.apply_mapping_pilot_result(session, root, approved_model=audit.MODEL_ID)
    assert result == {"status": "already_applied", "assignment_id": 2, "event_id": 3}
    verify.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_report_change_after_attestation_is_rejected_before_db_mutation(harness, monkeypatch):
    root = _report(harness, monkeypatch)
    assignment = SimpleNamespace(id=2, review_state="pending_model_review", evidence_ids=[10])
    session = Mock(new=set(), dirty=set(), deleted=set())
    session.scalar.side_effect = [SimpleNamespace(id=1), assignment, None]

    def live_packet(*_):
        _rewrite(root / "primary/response.raw.json", {**_opinion(), "conditions": ["Changed"]})
        return harness.payload

    monkeypatch.setattr(workflow, "mapping_review_input", live_packet)
    with pytest.raises(ValueError):
        workflow.apply_mapping_pilot_result(session, root, approved_model=audit.MODEL_ID)
    assert assignment.review_state == "pending_model_review"
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_different_valid_report_cannot_replace_the_previously_read_opinion(harness, monkeypatch):
    first = _report(harness, monkeypatch)
    harness.opinions["primary"] = {**_opinion(), "reasoning_summary": "Second synthetic opinion"}
    second = _report(harness, monkeypatch)
    original = pilot.validate_mapping_pilot_artifacts
    monkeypatch.setattr(
        workflow,
        "validate_mapping_pilot_artifacts",
        lambda *args, **kwargs: original(second, **kwargs),
    )
    assignment = SimpleNamespace(id=2, review_state="pending_model_review", evidence_ids=[10])
    session = Mock(new=set(), dirty=set(), deleted=set())
    session.scalar.side_effect = [SimpleNamespace(id=1), assignment, None]
    monkeypatch.setattr(workflow, "mapping_review_input", lambda *_: harness.payload)
    with pytest.raises(ValueError, match="mapping_report_changed_before_attestation"):
        workflow.apply_mapping_pilot_result(session, first, approved_model=audit.MODEL_ID)
    assert assignment.review_state == "pending_model_review"
    session.add.assert_not_called()
    session.commit.assert_not_called()
