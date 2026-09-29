from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelCapability:
    provider: str
    model_id: str
    model_version: str
    reasoning_tier: str
    context_window: int
    structured_output_supported: bool
    tool_call_supported: bool
    availability: str
    approved_for_review: bool
    capability_rank: int
    effective_at: str


@dataclass(frozen=True)
class ModelResolution:
    status: str
    model: ModelCapability | None
    fallback_used: bool
    reason: str


def load_registry(path: Path) -> tuple[list[ModelCapability], bool]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ValueError("model registry must contain a models list")
    required = set(ModelCapability.__dataclass_fields__)
    models: list[ModelCapability] = []
    for raw in payload["models"]:
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError("model capability fields are missing or unknown")
        model = ModelCapability(**raw)
        if model.availability not in {"available", "unavailable", "requires_probe"}:
            raise ValueError(f"invalid availability for {model.model_id}")
        if model.context_window <= 0 or model.capability_rank < 0:
            raise ValueError(f"invalid capacity for {model.model_id}")
        models.append(model)
    if len({model.model_id for model in models}) != len(models):
        raise ValueError("duplicate model id")
    allow_fallback = payload.get("allow_review_model_fallback", False)
    if not isinstance(allow_fallback, bool):
        raise ValueError("allow_review_model_fallback must be boolean")
    return models, allow_fallback


def resolve_model(
    models: list[ModelCapability],
    *,
    verified_available: set[str],
    allow_fallback: bool = False,
) -> ModelResolution:
    approved = sorted(
        (model for model in models if model.approved_for_review),
        key=lambda model: model.capability_rank,
        reverse=True,
    )
    if not approved:
        return ModelResolution("BLOCKED", None, False, "no approved review model")
    highest = approved[0]
    if highest.model_id in verified_available:
        return ModelResolution("AVAILABLE", highest, False, "highest approved model verified")
    if not allow_fallback:
        return ModelResolution(
            "BLOCKED", highest, False, "highest model unavailable; fallback disabled"
        )
    for model in approved[1:]:
        if model.model_id in verified_available:
            return ModelResolution("AVAILABLE", model, True, "explicit fallback enabled")
    return ModelResolution("BLOCKED", highest, False, "no verified approved model available")


def probe_codex_cli(model_id: str, *, timeout_seconds: int = 90) -> dict[str, Any]:
    executable = shutil.which("codex")
    if executable is None:
        return {"available": False, "reason": "Codex CLI not installed"}
    command = [
        executable,
        "exec",
        "-m",
        model_id,
        "-c",
        'model_reasoning_effort="max"',
        "--ephemeral",
        "-s",
        "read-only",
        "--skip-git-repo-check",
        "Reply exactly REVIEW_MODEL_READY and do not use tools.",
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": type(exc).__name__}
    combined = completed.stdout + completed.stderr
    # A CLI banner alone is not proof of a successful model response.
    available = completed.returncode == 0 and "REVIEW_MODEL_READY" in completed.stdout
    version_line = next(
        (line for line in combined.splitlines() if line.startswith("OpenAI Codex v")), None
    )
    return {
        "available": available,
        "reason": "probe response verified" if available else "model probe failed",
        "cli_version": version_line,
        "exit_code": completed.returncode,
    }


def resolution_payload(resolution: ModelResolution, probe: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "status": resolution.status,
        "provider": resolution.model.provider if resolution.model else None,
        "model_id": resolution.model.model_id if resolution.model else None,
        "model_version": resolution.model.model_version if resolution.model else None,
        "reasoning_tier": resolution.model.reasoning_tier if resolution.model else None,
        "fallback_used": resolution.fallback_used,
        "reason": resolution.reason,
        "probe": probe,
        "snapshot_pinned": bool(
            resolution.model and resolution.model.model_version != "alias_unresolved"
        ),
    }


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
