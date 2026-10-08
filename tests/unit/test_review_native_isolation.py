"""Synthetic-only tests for the version-pinned isolated native review adapter."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cloud_expert.model_review import reproducibility as audit
from tests.unit.test_model_reproducibility import SyntheticBundle


def isolated_metadata(bundle: Any) -> audit.ExecutionMetadata:
    from cloud_expert.model_review.isolated_runtime import isolated_config_args

    data = deepcopy(bundle.executions["primary"])
    root = Path(data["cwd"])
    data.update(
        cwd=str(root / "work"),
        schema_path=str(root / "work" / "schema.json"),
        response_path=str(root / "work" / "response.json"),
        runtime_isolation={
            "schema_version": "isolated_review_runtime.v1",
            "home": str(root / "home"),
            "fresh_home": True,
            "sanitized_environment": True,
            "private_permissions": True,
            "credential_copy_only": True,
            "environment_keys": ["PATH", "CODEX_HOME"],
        },
    )
    data["argv"] = [
        data["argv"][0],
        "exec",
        "-m",
        audit.MODEL_ID,
        "-c",
        'model_reasoning_effort="max"',
        *isolated_config_args(root / "home"),
        "--output-schema",
        data["schema_path"],
        "-o",
        data["response_path"],
        "-",
    ]
    data["argv_sha256"] = audit.object_sha256(data["argv"])
    return audit.ExecutionMetadata.model_validate(data)


def test_legacy_argv_cannot_claim_production_isolation(tmp_path: Path) -> None:
    bundle = SyntheticBundle(tmp_path)
    meta = audit.ExecutionMetadata.model_validate(bundle.executions["primary"])
    audit._argv(meta)
    with pytest.raises(audit.BundleError, match="runtime_isolation_required"):
        audit._argv(meta, require_isolation=True)


def test_isolated_argv_requires_attestation_and_native_capture(tmp_path: Path) -> None:
    meta = isolated_metadata(SyntheticBundle(tmp_path))
    audit._argv(meta, has_runtime_identity=True, require_isolation=True)
    with pytest.raises(audit.BundleError):
        audit._argv(meta, has_runtime_identity=False)


@pytest.mark.parametrize(
    "field",
    [
        "fresh_home",
        "sanitized_environment",
        "private_permissions",
        "credential_copy_only",
    ],
)
def test_negative_launcher_attestation_fails(tmp_path: Path, field: str) -> None:
    meta = isolated_metadata(SyntheticBundle(tmp_path))
    assert meta.runtime_isolation is not None
    setattr(meta.runtime_isolation, field, False)
    with pytest.raises(audit.BundleError, match="runtime_isolation_attestation_invalid"):
        audit._argv(meta, has_runtime_identity=True)


@pytest.mark.parametrize(
    "keys",
    [
        ["PATH"],
        ["CODEX_HOME", "CODEX_THREAD_ID"],
        ["CODEX_HOME", "API_KEY"],
        ["CODEX_HOME", "Path", "PATH"],
        ["CODEX_HOME", "PYTHONPATH"],
    ],
)
def test_inherited_or_ambiguous_environment_fails(tmp_path: Path, keys: list[str]) -> None:
    meta = isolated_metadata(SyntheticBundle(tmp_path))
    assert meta.runtime_isolation is not None
    meta.runtime_isolation.environment_keys = keys
    with pytest.raises(audit.BundleError, match="runtime_environment_not_isolated"):
        audit._argv(meta, has_runtime_identity=True)


@pytest.mark.parametrize("mutation", ["home", "cwd", "schema", "response", "argv", "hash"])
def test_isolated_paths_and_command_are_bound(tmp_path: Path, mutation: str) -> None:
    meta = isolated_metadata(SyntheticBundle(tmp_path))
    assert meta.runtime_isolation is not None
    if mutation == "home":
        meta.runtime_isolation.home = str(tmp_path / "another" / "home")
    elif mutation == "cwd":
        meta.cwd = str(tmp_path / "another" / "work")
    elif mutation == "schema":
        meta.schema_path = str(tmp_path / "outside.json")
    elif mutation == "response":
        meta.response_path = meta.schema_path
    elif mutation == "argv":
        meta.argv.insert(-1, "--ephemeral")
        meta.argv_sha256 = audit.object_sha256(meta.argv)
    else:
        meta.argv_sha256 = "0" * 64
    with pytest.raises(audit.BundleError):
        audit._argv(meta, has_runtime_identity=True)


def synthetic_native_events(
    *,
    cwd: str,
    session_id: str,
    turn_id: str,
    prompt: str,
    response: str,
    started_at: str,
    completed_at: str,
    cli_version: str = "0.158.0-synthetic",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pure fixture factory; returned hashes pin synthetic boilerplate, not real logs."""
    meta = SimpleNamespace(cwd=cwd, session_id=session_id, started_at=started_at)
    session = {
        "id": session_id,
        "cwd": cwd,
        "model_provider": "openai",
        "cli_version": cli_version,
        "parent_thread_id": None,
    }
    context = {
        "turn_id": turn_id,
        "root_turn_id": turn_id,
        "cwd": cwd,
        "model": audit.MODEL_ID,
        "effort": "max",
    }
    session.update(
        creator_user_id="synthetic_user",
        creator_account_id="synthetic_account",
        session_id=meta.session_id,
        timestamp=meta.started_at,
        runtime_workspace_roots=[meta.cwd],
        context_window={"window_id": turn_id},
    )
    context.update(
        workspace_roots=[meta.cwd],
        current_date=audit._time(started_at).date().isoformat(),
        timezone="UTC",
    )
    date = context["current_date"]
    fs = (
        "<filesystem><workspace_roots><root>" + meta.cwd + "</root></workspace_roots>"
        '<permission_profile type="managed"><file_system type="restricted">'
        '<entry access="read"><special>:root</special></entry></file_system>'
        "</permission_profile></filesystem>"
    )
    environment = (
        f"<environment_context><cwd>{meta.cwd}</cwd><shell>powershell</shell>"
        f"<current_date>{date}</current_date><timezone>UTC</timezone>{fs}</environment_context>"
    )
    world = {
        "full": True,
        "state": {
            "permissions": {"approved_command_prefixes": []},
            "agents_md": {},
            "managed_developer_instructions": {},
            "persistent_mode": {},
            "host_skills": {"body": "", "includeInstructions": False},
            "environments": {
                "environments": {"local": {"cwd": meta.cwd, "shell": "powershell"}},
                "current_date": date,
                "timezone": "UTC",
                "filesystem": fs,
            },
        },
    }

    def event(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": kind, "timestamp": meta.started_at, "payload": payload}

    def message(role: str, text: str, name: str) -> dict[str, Any]:
        return event(
            "response_item",
            {
                "type": "message",
                "role": role,
                "id": "synthetic-" + name,
                "content": [{"type": "input_text", "text": text}],
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": context["turn_id"],
                    "create_time": datetime.fromisoformat(meta.started_at).timestamp(),
                    "content_item_kinds": [name],
                },
            },
        )

    developers = [
        message("developer", "SYNTHETIC fixed instruction " + str(i), "fixed" + str(i))
        for i in range(3)
    ]
    developers[0]["payload"]["content"].append(
        {"type": "input_text", "text": "SYNTHETIC second fixed part"}
    )
    developers[0]["payload"]["internal_chat_message_metadata_passthrough"][
        "content_item_kinds"
    ].append("fixed0b")
    events = [
        event("session_meta", session),
        event("event_msg", {"type": "task_started", "turn_id": turn_id, "root_turn_id": turn_id}),
        *developers,
        message("user", environment, "environment"),
        event("world_state", world),
        event("turn_context", context),
        message("user", prompt, "prompt"),
        event(
            "event_msg",
            {
                "type": "item_completed",
                "thread_id": meta.session_id,
                "turn_id": context["turn_id"],
                "item": {
                    "type": "UserMessage",
                    "id": turn_id,
                    "content": [{"type": "text", "text": prompt, "text_elements": []}],
                },
            },
        ),
        event(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "channel": "final",
                "content": [{"type": "output_text", "text": response}],
            },
        ),
        {
            "type": "event_msg",
            "timestamp": completed_at,
            "payload": {
                "type": "task_complete",
                "turn_id": turn_id,
                "last_agent_message": response,
            },
        },
    ]

    def norm(text: str) -> str:
        return text.replace(meta.cwd, "{CWD}").replace(date, "{DATE}")

    s = deepcopy(session)
    s.update(
        creator_user_id="{LOCAL_AUTH_METADATA}",
        creator_account_id="{LOCAL_AUTH_METADATA}",
        id="{SESSION}",
        session_id="{SESSION}",
        timestamp="{TIMESTAMP}",
        cwd="{CWD}",
        runtime_workspace_roots=["{CWD}"],
        context_window={"window_id": "{WINDOW}"},
    )
    c = deepcopy(context)
    c.update(
        turn_id="{TURN}",
        root_turn_id="{TURN}",
        cwd="{CWD}",
        workspace_roots=["{CWD}"],
        current_date="{DATE}",
    )
    w = deepcopy(world)
    w["state"]["environments"]["environments"]["local"]["cwd"] = "{CWD}"
    w["state"]["environments"].update(current_date="{DATE}", filesystem=norm(fs))
    profile = {
        "session": audit.object_sha256(s),
        "context": audit.object_sha256(c),
        "world": audit.object_sha256(w),
        "developers": [
            {
                "texts": [
                    sha256(part["text"].encode()).hexdigest() for part in d["payload"]["content"]
                ],
                "kinds": audit.object_sha256(
                    d["payload"]["internal_chat_message_metadata_passthrough"]["content_item_kinds"]
                ),
            }
            for i, d in enumerate(developers)
        ],
        "environment": {
            "text": sha256(norm(environment).encode()).hexdigest(),
            "kinds": audit.object_sha256(["environment"]),
        },
        "prompt": {"kinds": audit.object_sha256(["prompt"])},
    }
    events[2]["metadata"] = {"client_authored": False, "mcp_attribution": {"status": "none"}}
    for index, order in ((8, 0), (10, 1)):
        payload = events[index]["payload"]
        payload.setdefault("id", "synthetic-final")
        events[index]["metadata"] = {
            "client_authored": False,
            "user_input_order": order,
            "retained_source": {
                "id": {"message_id": payload["id"], "turn_id": turn_id, "role": payload["role"]},
                "revision": "revision_" + turn_id,
                "complete": True,
            },
        }
    envelope_hashes = {}
    retained_false_hashes = {}
    for index in (2, 8, 10):
        metadata = deepcopy(events[index]["metadata"])
        if "retained_source" in metadata:
            retained = metadata["retained_source"]
            retained["id"].update(message_id="{MESSAGE}", turn_id="{TURN}")
            retained["revision"] = "revision_{REVISION}"
        envelope_hashes[events[index]["payload"]["role"]] = audit.object_sha256(metadata)
        if "retained_source" in metadata:
            metadata["retained_source"]["complete"] = False
            retained_false_hashes[events[index]["payload"]["role"]] = audit.object_sha256(metadata)
    profile["envelope_metadata"] = envelope_hashes
    profile["retained_false_metadata"] = retained_false_hashes
    profile["developers"][0]["envelope"] = envelope_hashes["developer"]
    profile["prompt"]["envelope"] = envelope_hashes["user"]
    assistant = events[10]["payload"]
    assistant["phase"] = "SYNTHETIC final"
    assistant["internal_chat_message_metadata_passthrough"] = {
        "turn_id": turn_id,
        "create_time": datetime.fromisoformat(started_at).timestamp(),
        "content_item_kinds": ["synthetic_assistant"],
    }
    profile["assistant_output"] = {
        "keys": sorted(assistant),
        "phase": audit.object_sha256(assistant["phase"]),
        "kinds": audit.object_sha256(["synthetic_assistant"]),
    }
    for ordinal, native_event in enumerate(events):
        native_event["ordinal"] = ordinal
    return events, profile


@pytest.fixture
def clean_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    bundle = SyntheticBundle(tmp_path)
    meta = isolated_metadata(bundle)
    bundle.executions["primary"] = meta.model_dump()
    bundle.attach_runtime_identity("primary")
    refs = bundle.manifest["stages"]["primary"]
    events, profile = synthetic_native_events(
        cwd=meta.cwd,
        session_id=meta.session_id,
        turn_id=bundle.runtime_captures["primary"]["turn_id"],
        prompt=(tmp_path / refs["prompt"]["path"]).read_text(),
        response=(tmp_path / refs["response"]["path"]).read_text(),
        started_at=meta.started_at,
        completed_at=meta.completed_at,
    )
    monkeypatch.setattr(audit, "_CLEAN_NATIVE_PROFILE", profile)
    bundle.runtime_traces["primary"] = events
    bundle.save_runtime("primary")
    bundle.seal()
    return bundle


def test_synthetic_clean_native_passes_without_mutating_capture(clean_bundle: Any) -> None:
    original = deepcopy(clean_bundle.runtime_traces["primary"])
    assert clean_bundle.check()["status"] == "SYNTHETIC_VERIFIED"
    assert clean_bundle.runtime_traces["primary"] == original


def _set_retained_complete(bundle: Any, value: bool | tuple[bool, bool]) -> list[dict[str, Any]]:
    events = bundle.runtime_traces["primary"]
    values = (value, value) if isinstance(value, bool) else value
    for index, complete in zip((8, 10), values, strict=True):
        events[index]["metadata"]["retained_source"]["complete"] = complete
    return events


def test_observed_retained_false_profile_requires_full_evidence(clean_bundle: Any) -> None:
    events = _set_retained_complete(clean_bundle, False)
    original = deepcopy(events)
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "SYNTHETIC_VERIFIED"
    assert events == original


@pytest.mark.parametrize("flags", [(True, True), (False, False), (False, True), (True, False)])
def test_retention_flags_are_independent_of_full_text_proof(
    clean_bundle: Any, flags: tuple[bool, bool]
) -> None:
    events = _set_retained_complete(clean_bundle, flags)
    original = deepcopy(events)
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "SYNTHETIC_VERIFIED"
    assert events == original


def test_retained_false_requires_explicit_profile(
    clean_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_retained_complete(clean_bundle, False)
    profile = deepcopy(audit._CLEAN_NATIVE_PROFILE)
    del profile["retained_false_metadata"]
    monkeypatch.setattr(audit, "_CLEAN_NATIVE_PROFILE", profile)
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["errors"] == ["runtime_clean_envelope_invalid"]


@pytest.mark.parametrize("complete", [(True, True), (False, False), (False, True), (True, False)])
@pytest.mark.parametrize("duplicate", ["prompt", "user_item", "assistant", "completion"])
@pytest.mark.parametrize("mutation", ["truncate", "leading_space", "trailing_newline"])
def test_retained_text_requires_exact_bytes_in_each_duplicate(
    clean_bundle: Any, complete: tuple[bool, bool], duplicate: str, mutation: str
) -> None:
    events = _set_retained_complete(clean_bundle, complete)
    if duplicate == "completion":
        container, key = events[11]["payload"], "last_agent_message"
    elif duplicate == "user_item":
        container, key = events[9]["payload"]["item"]["content"][0], "text"
    else:
        index = 8 if duplicate == "prompt" else 10
        container, key = events[index]["payload"]["content"][0], "text"
    text = container[key]
    container[key] = {
        "truncate": text[:-1],
        "leading_space": " " + text,
        "trailing_newline": text + "\n",
    }[mutation]
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "BLOCKED"


@pytest.mark.parametrize("index", [8, 10])
@pytest.mark.parametrize("value", [None, 0, 1, "false", "true", [], {}])
def test_retained_completeness_is_strict_boolean(clean_bundle: Any, index: int, value: Any) -> None:
    events = _set_retained_complete(clean_bundle, False)
    events[index]["metadata"]["retained_source"]["complete"] = value
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["errors"] == ["runtime_retained_source_invalid"]


@pytest.mark.parametrize("complete", [(True, True), (False, False), (False, True), (True, False)])
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_assistant",
        "missing_completion",
        "duplicate_completion",
        "completion_turn",
        "completion_time",
        "completion_not_last",
        "missing_user_item",
    ],
)
def test_retained_profile_requires_bound_complete_turn(
    clean_bundle: Any, complete: tuple[bool, bool], mutation: str
) -> None:
    events = _set_retained_complete(clean_bundle, complete)
    if mutation == "missing_assistant":
        events.pop(10)
    elif mutation == "missing_completion":
        events.pop(11)
    elif mutation == "duplicate_completion":
        events.append(deepcopy(events[11]))
    elif mutation == "completion_turn":
        events[11]["payload"]["turn_id"] = "SYNTHETIC-wrong-turn"
    elif mutation == "completion_time":
        events[11]["timestamp"] = "2026-09-29T00:00:00+00:00"
    elif mutation == "completion_not_last":
        events[10], events[11] = events[11], events[10]
    elif mutation == "missing_user_item":
        events.pop(9)
    for ordinal, event in enumerate(events):
        event["ordinal"] = ordinal
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "BLOCKED"


@pytest.mark.parametrize("index", [8, 10])
@pytest.mark.parametrize(
    "mutation",
    [
        "message_id",
        "turn_id",
        "role",
        "extra",
        "missing",
        "revision",
        "revision_prefix",
        "retained_extra",
        "id_extra",
        "client_authored",
        "order",
    ],
)
def test_retained_false_preserves_exact_metadata_bindings(
    clean_bundle: Any, index: int, mutation: str
) -> None:
    event = _set_retained_complete(clean_bundle, False)[index]
    retained = event["metadata"]["retained_source"]
    if mutation == "extra":
        event["metadata"]["unknown"] = False
    elif mutation == "missing":
        del retained["complete"]
    elif mutation == "revision":
        retained["revision"] = "SYNTHETIC malformed revision"
    elif mutation == "revision_prefix":
        retained["revision"] = "abcdefgh_" + retained["revision"].split("_", 1)[1]
    elif mutation == "retained_extra":
        retained["unknown"] = False
    elif mutation == "id_extra":
        retained["id"]["unknown"] = False
    elif mutation == "client_authored":
        event["metadata"]["client_authored"] = True
    elif mutation == "order":
        event["metadata"]["user_input_order"] = 2
    else:
        retained["id"][mutation] = "SYNTHETIC-wrong-binding"
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "BLOCKED"


@pytest.mark.parametrize("field", ["prompt_sha256", "response_sha256"])
def test_clean_native_text_is_bound_to_execution_hash(clean_bundle: Any, field: str) -> None:
    _set_retained_complete(clean_bundle, False)
    clean_bundle.executions["primary"][field] = "0" * 64
    clean_bundle.save_runtime("primary")
    refs = clean_bundle.manifest["stages"]["primary"]
    with pytest.raises(audit.BundleError, match="execution_artifact_hash_mismatch"):
        audit._runtime_identity(
            audit._Reader(clean_bundle.root),
            audit.RuntimeIdentityEvidence.model_validate(refs["runtime_identity"]),
            audit.ExecutionMetadata.model_validate(clean_bundle.executions["primary"]),
            (clean_bundle.root / refs["prompt"]["path"]).read_bytes().decode("utf-8"),
            (clean_bundle.root / refs["response"]["path"]).read_bytes(),
            clean_bundle.manifest["release"]["frozen_at"],
            require_isolation=True,
        )


def test_unreviewed_profile_never_accepts(
    clean_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "_CLEAN_NATIVE_PROFILE", {})
    result = clean_bundle.check()
    assert result["status"] == "BLOCKED"
    assert result["errors"] == ["runtime_clean_profile_unavailable"]


def test_unobserved_native_schema_field_is_not_silently_ignored(clean_bundle: Any) -> None:
    clean_bundle.runtime_traces["primary"][7]["payload"]["final_output_json_schema"] = {
        "type": "object",
        "properties": {"synthetic": {"type": "string"}},
    }
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    result = clean_bundle.check()
    assert result["status"] == "BLOCKED"
    assert result["errors"] == ["runtime_clean_context_invalid"]


@pytest.mark.parametrize("mutation", ["second_part", "merge", "remove", "reverse"])
def test_all_generated_developer_parts_are_bound(clean_bundle: Any, mutation: str) -> None:
    content = clean_bundle.runtime_traces["primary"][2]["payload"]["content"]
    if mutation == "second_part":
        content[1]["text"] += "SYNTHETIC injected"
    elif mutation == "merge":
        content[0]["text"] += content.pop()["text"]
    elif mutation == "remove":
        content.pop()
    else:
        content.reverse()
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    result = clean_bundle.check()
    assert result["status"] == "BLOCKED"
    assert result["errors"] == ["runtime_developer_text_invalid"]


@pytest.mark.parametrize(
    "mutation",
    [
        "rules",
        "skills",
        "agents",
        "managed",
        "persistent",
        "world_extra",
        "world_missing",
        "world_duplicate",
        "world_order",
        "world_partial",
        "world_model",
        "world_cwd",
        "world_date",
        "world_timezone",
        "world_filesystem",
        "world_type",
        "session_extra",
        "session_model",
        "session_cwd",
        "session_roots",
        "session_id",
        "session_time",
        "session_instructions",
        "auth_shape",
        "auth_missing",
        "context_extra",
        "context_model",
        "context_effort",
        "context_turn",
        "context_roots",
        "context_date",
        "context_timezone",
        "context_permission",
        "context_duplicate",
        "developer_text",
        "developer_extra",
        "developer_missing",
        "developer_role",
        "environment_text",
        "environment_xml",
        "environment_cwd",
        "environment_duplicate",
        "prompt_text",
        "prompt_missing",
        "prompt_extra",
        "prompt_prior",
        "message_extra_key",
        "message_content_extra",
        "message_id_duplicate",
        "message_kind",
        "message_turn",
        "message_time",
        "message_secret",
        "user_item_text",
        "user_item_id",
        "user_item_extra",
        "user_item_duplicate",
        "user_item_missing",
        "tool",
        "unknown_event",
        "fallback",
        "second_turn",
    ],
)
def test_clean_native_rejects_tampering(clean_bundle: Any, mutation: str) -> None:
    events = clean_bundle.runtime_traces["primary"]
    session, world, context = events[0]["payload"], events[6]["payload"], events[7]["payload"]
    state = world["state"]
    if mutation in {"rules", "skills", "agents", "managed", "persistent"}:
        if mutation == "rules":
            state["permissions"]["approved_command_prefixes"] = [["synthetic"]]
        elif mutation == "skills":
            state["host_skills"]["body"] = "SYNTHETIC inherited catalog"
        else:
            state[
                {
                    "agents": "agents_md",
                    "managed": "managed_developer_instructions",
                    "persistent": "persistent_mode",
                }[mutation]
            ] = {"extra": "SYNTHETIC"}
    elif mutation == "world_extra":
        state["extra"] = False
    elif mutation == "world_missing":
        events.pop(6)
    elif mutation == "world_duplicate":
        events.insert(6, deepcopy(events[6]))
    elif mutation == "world_order":
        events[6], events[7] = events[7], events[6]
    elif mutation == "world_partial":
        world["full"] = False
    elif mutation == "world_model":
        state["model"] = "other"
    elif mutation == "world_cwd":
        state["environments"]["environments"]["local"]["cwd"] += "-other"
    elif mutation in {"world_date", "world_timezone", "world_filesystem"}:
        state["environments"][
            {
                "world_date": "current_date",
                "world_timezone": "timezone",
                "world_filesystem": "filesystem",
            }[mutation]
        ] = "SYNTHETIC wrong"
    elif mutation == "world_type":
        world["state"] = []
    elif mutation.startswith("session_"):
        key = {
            "session_extra": "extra",
            "session_model": "model_provider",
            "session_cwd": "cwd",
            "session_roots": "runtime_workspace_roots",
            "session_id": "session_id",
            "session_time": "timestamp",
            "session_instructions": "base_instructions",
        }[mutation]
        session[key] = "SYNTHETIC changed"
    elif mutation == "auth_shape":
        session["creator_user_id"] = {"secret": "SYNTHETIC"}
    elif mutation == "auth_missing":
        del session["creator_account_id"]
    elif mutation == "context_duplicate":
        events.insert(8, deepcopy(events[7]))
    elif mutation.startswith("context_"):
        key = {
            "context_extra": "extra",
            "context_model": "model",
            "context_effort": "effort",
            "context_turn": "turn_id",
            "context_roots": "workspace_roots",
            "context_date": "current_date",
            "context_timezone": "timezone",
            "context_permission": "permission_profile",
        }[mutation]
        context[key] = "SYNTHETIC changed"
    elif mutation == "developer_text":
        events[2]["payload"]["content"][0]["text"] += " "
    elif mutation == "developer_extra":
        events.insert(9, deepcopy(events[2]))
    elif mutation == "developer_missing":
        events.pop(2)
    elif mutation == "developer_role":
        events[2]["payload"]["role"] = "system"
    elif mutation in {"environment_text", "environment_xml", "environment_cwd"}:
        events[5]["payload"]["content"][0]["text"] += {
            "environment_text": "SYNTHETIC injected",
            "environment_xml": "<!-- extra -->",
            "environment_cwd": "{CWD}",
        }[mutation]
    elif mutation == "environment_duplicate":
        events.insert(9, deepcopy(events[5]))
    elif mutation == "prompt_text":
        events[8]["payload"]["content"][0]["text"] += " "
    elif mutation == "prompt_missing":
        events.pop(8)
    elif mutation == "prompt_extra":
        events.insert(9, deepcopy(events[8]))
    elif mutation == "prompt_prior":
        events[5], events[8] = events[8], events[5]
    elif mutation == "message_extra_key":
        events[2]["payload"]["extra"] = False
    elif mutation == "message_content_extra":
        events[2]["payload"]["content"].append({"type": "image"})
    elif mutation == "message_id_duplicate":
        events[3]["payload"]["id"] = events[2]["payload"]["id"]
    elif mutation.startswith("message_"):
        key = {
            "message_kind": "content_item_kinds",
            "message_turn": "turn_id",
            "message_time": "create_time",
            "message_secret": "api_key",
        }[mutation]
        events[2]["payload"]["internal_chat_message_metadata_passthrough"][key] = "SYNTHETIC wrong"
    elif mutation == "user_item_text":
        events[9]["payload"]["item"]["content"][0]["text"] += " "
    elif mutation == "user_item_id":
        events[9]["payload"]["item"]["id"] = "other"
    elif mutation == "user_item_extra":
        events[9]["payload"]["item"]["extra"] = False
    elif mutation == "user_item_duplicate":
        events.insert(10, deepcopy(events[9]))
    elif mutation == "user_item_missing":
        events.pop(9)
    elif mutation == "tool":
        events[9]["payload"]["item"]["type"] = "CommandExecution"
    elif mutation == "unknown_event":
        unknown = deepcopy(events[10])
        unknown["type"] = "compacted"
        events.insert(10, unknown)
    elif mutation == "fallback":
        context["fallback_used"] = True
    elif mutation == "second_turn":
        events.insert(10, deepcopy(events[1]))
    for ordinal, native_event in enumerate(events):
        native_event["ordinal"] = ordinal
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "ordinal_bool",
        "ordinal_string",
        "ordinal_duplicate",
        "ordinal_decreasing",
        "payload_type",
        "timestamp_type",
        "type_type",
    ],
)
def test_clean_native_envelopes_fail_closed(clean_bundle: Any, mutation: str) -> None:
    events = clean_bundle.runtime_traces["primary"]
    event = events[3]
    if mutation == "extra":
        event["hidden_input"] = "SYNTHETIC extra"
    elif mutation == "missing":
        del event["ordinal"]
    elif mutation == "ordinal_bool":
        event["ordinal"] = True
    elif mutation == "ordinal_string":
        event["ordinal"] = "3"
    elif mutation == "ordinal_duplicate":
        event["ordinal"] = events[2]["ordinal"]
    elif mutation == "ordinal_decreasing":
        event["ordinal"] = -1
    elif mutation == "payload_type":
        event["payload"] = []
    elif mutation == "timestamp_type":
        event["timestamp"] = 12
    else:
        event["type"] = []
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "flag",
    [
        'model_reasoning_effort="max"',
        'cli_auth_credentials_store="file"',
        "suppress_unstable_features_warning=true",
        "skip_host_skill_discovery",
        "goals",
        "sleep_tool",
        "tool_suggest",
    ],
)
def test_isolated_required_command_controls_cannot_change(tmp_path: Path, flag: str) -> None:
    meta = isolated_metadata(SyntheticBundle(tmp_path))
    meta.argv[meta.argv.index(flag)] = "SYNTHETIC unsafe replacement"
    meta.argv_sha256 = audit.object_sha256(meta.argv)
    with pytest.raises(audit.BundleError, match="execution_argv_unsafe"):
        audit._argv(meta, has_runtime_identity=True, require_isolation=True)


def test_production_bundle_cannot_use_legacy_attestation(tmp_path: Path) -> None:
    bundle = SyntheticBundle(tmp_path)
    bundle.manifest["data_classification"] = "official_public"
    bundle.packet["data_classification"] = "official_public"
    bundle.rebind_packet()
    result = bundle.check()
    assert result["status"] == "BLOCKED"
    assert "runtime_isolation_required" in str(result)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "role",
        "turn",
        "message",
        "complete",
        "revision",
        "client_authored",
        "order",
        "mcp",
        "unobserved_event",
        "wrong_type",
    ],
)
def test_native_envelope_metadata_is_narrowly_bound(clean_bundle: Any, mutation: str) -> None:
    events = clean_bundle.runtime_traces["primary"]
    metadata = events[8]["metadata"]
    if mutation == "extra":
        metadata["extra"] = "SYNTHETIC hidden"
    elif mutation == "missing":
        del events[8]["metadata"]
    elif mutation in {"role", "turn", "message"}:
        metadata["retained_source"]["id"][
            {"role": "role", "turn": "turn_id", "message": "message_id"}[mutation]
        ] = "SYNTHETIC other"
    elif mutation == "complete":
        metadata["retained_source"]["complete"] = "false"
    elif mutation == "revision":
        metadata["retained_source"]["revision"] = "SYNTHETIC arbitrary text"
    elif mutation == "client_authored":
        metadata["client_authored"] = True
    elif mutation == "order":
        metadata["user_input_order"] = 2
    elif mutation == "mcp":
        metadata["mcp_attribution"] = {"status": "SYNTHETIC other"}
    elif mutation == "unobserved_event":
        events[6]["metadata"] = deepcopy(events[2]["metadata"])
    else:
        events[8]["metadata"] = []
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "BLOCKED"


@pytest.mark.parametrize("mutation", ["turn", "time", "kind", "phase", "extra"])
def test_assistant_output_metadata_is_bound(clean_bundle: Any, mutation: str) -> None:
    payload = clean_bundle.runtime_traces["primary"][10]["payload"]
    if mutation == "phase":
        payload["phase"] = "SYNTHETIC commentary"
    elif mutation == "extra":
        payload["status"] = "failed"
    else:
        payload["internal_chat_message_metadata_passthrough"][
            {
                "turn": "turn_id",
                "time": "create_time",
                "kind": "content_item_kinds",
            }[mutation]
        ] = "SYNTHETIC wrong"
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "BLOCKED"


def test_assistant_creation_clock_is_not_execution_window_proof(clean_bundle: Any) -> None:
    event = clean_bundle.runtime_traces["primary"][10]
    event["payload"]["internal_chat_message_metadata_passthrough"]["create_time"] -= 10
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == "SYNTHETIC_VERIFIED"
    event["timestamp"] = "2026-09-29T00:00:00+00:00"
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    result = clean_bundle.check()
    assert result["status"] == "BLOCKED"
    assert result["errors"] == ["runtime_event_time_invalid"]


def test_output_id_binding_cannot_be_vacuously_null(clean_bundle: Any) -> None:
    event = clean_bundle.runtime_traces["primary"][10]
    event["payload"]["id"] = None
    event["metadata"]["retained_source"]["id"]["message_id"] = None
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["errors"] == ["runtime_retained_source_invalid"]


@pytest.mark.parametrize("mutation", [None, "turn", "extra"])
def test_reasoning_output_is_known_type_with_same_turn(
    clean_bundle: Any, mutation: str | None
) -> None:
    events = clean_bundle.runtime_traces["primary"]
    payload = {
        "type": "reasoning",
        "id": "rs_synthetic",
        "summary": [],
        "encrypted_content": "SYNTHETIC placeholder, not real reasoning",
        "internal_chat_message_metadata_passthrough": {"turn_id": events[7]["payload"]["turn_id"]},
    }
    if mutation == "turn":
        payload["internal_chat_message_metadata_passthrough"]["turn_id"] = "other"
    elif mutation == "extra":
        payload["extra_input"] = "SYNTHETIC injected"
    events.insert(
        10, {"type": "response_item", "timestamp": events[9]["timestamp"], "payload": payload}
    )
    for ordinal, event in enumerate(events):
        event["ordinal"] = ordinal
    clean_bundle.save_runtime("primary")
    clean_bundle.seal()
    assert clean_bundle.check()["status"] == (
        "SYNTHETIC_VERIFIED" if mutation is None else "BLOCKED"
    )
