"""Read-only verification of the owner-authorized INTERNAL RC alias alternative.

Builder/integration contract (``audit_bundle_schema()`` exports the schemas):

1. Freeze the DecisionPacket's input.json and fingerprint.json without changing
   its hash algorithm. Copy the exact public source snapshots into the audit
   directory; retain Evidence/SourceDocument identifiers and excerpt hashes.
   Freeze code, rules, data and the complete evaluation case inventory as files.
2. Run primary/adversarial in new, isolated contexts. Preserve prompt templates,
   exact prompts, schemas, full raw responses, execution.json, stdout JSONL and
   stderr. On disagreement run isolated arbitration with both complete opinions.
   Identity may come from stdout turn.started OR a captured native session JSONL
   (session_meta.model_provider + turn_context.model). For the latter attach
   runtime_identity.trace and runtime_identity.capture; see the exported capture
   schema. Both must bind the same stage audit_id, thread, turn, cwd, time window,
   input and full response. Capture original runtime bytes, never reconstructed
   events. A requested -m flag, probe or banner is not model identity evidence.
   A runtime that exposes neither supported identity form remains BLOCKED.
   Non-synthetic stages additionally require runtime_isolation launcher attestation
   and the version-pinned clean native profile; legacy stdout-only proof is not
   sufficient. Generated environment input is separate from the exact review input.
3. Build AuditBundle with FileRefs (relative POSIX path + SHA-256 of file bytes).
   Set release.frozen_at after the reviews, then call
   compute_artifact_fingerprint(). This covers every pre-evaluation artifact,
   the unique release ID, cutoff, model alias, scope and drift disclosures.
4. Run the entire frozen evaluation plan AFTER frozen_at. Record every case,
   exact release ID/fingerprint, actual_model_identity_sha256(), start/end time,
   successful full-chain/model-judge execution and zero failures/skips. Hash the
   resulting evaluation file and publish the manifest last. Seal its byte hash
   in the coordinator's trusted release record OUTSIDE this bundle. Do not reuse runs.
5. The release coordinator independently supplies expected_release_id,
   expected_artifact_fingerprint, expected_subject_hash and the sealed
   expected_manifest_sha256 at consumption. Do NOT obtain those expectations
   from the untrusted manifest being checked.
   Recheck files at each consumption and preserve originals. This verifier does
   not write a Gate, approve a Decision, transfer data or touch the database.

JSON object fingerprints use sorted keys, ensure_ascii=False and Python's
default separators, matching decision_panel._hash. FileRefs hash exact bytes.
Hashes establish integrity/binding, not collector authenticity: storage and
runtime capture must be trusted. Detectable context reuse is rejected; this
cannot prove the absence of unrecorded context or reproduce model weights.
Native session files can contain account metadata: retain them locally under
access controls, never send them to model reviewers or read authentication files
to build a capture. The capture's source_basename is provenance only; the verifier
never follows it. It reads only hashed audit-relative attachments. The supported
session format was inspected locally in CLI 0.158.0 runtime metadata. Unknown
events, inherited context, tools, multiple turns and truncated captures fail closed.
If --ephemeral suppresses session files, an isolated non-resumed invocation may
omit it ONLY with a verified complete single-turn runtime_identity attachment.
The current panel must gain genuine trace/identity capture before it can pass.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cloud_expert.model_review.schemas import Decision

MODEL_ID = "gpt-6-astra"
SCHEMA_VERSION = "internal_rc_audit_bundle.v1"
DEFAULT_POLICY = (
    Path(__file__).resolve().parents[3] / "config/model_review/reproducibility_policy.yaml"
)
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
UUIDText = Annotated[str, Field(pattern=r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")]
Positive = Annotated[int, Field(gt=0)]
StageName = Literal["primary", "adversarial", "arbitration"]
REQUIRED_CONTROLS = {
    "freeze_review_input_and_prompt_versions",
    "preserve_full_primary_adversarial_and_arbitration_responses",
    "verify_evidence_and_artifact_sha256_at_consumption",
    "preserve_actual_model_identity_and_execution_metadata",
    "independently_review_generation_and_adversarial_contexts",
    "rerun_full_evaluation_for_every_release_candidate",
    "bind_evaluation_to_candidate_code_rules_data_and_model_identity",
    "disclose_alias_drift_and_nondeterministic_model_reexecution",
    "prohibit_customer_or_production_authority_from_this_policy_alone",
}
REQUIRED_EVAL_CATEGORIES = {
    "source",
    "parsing",
    "normalization",
    "comparability",
    "mapping",
    "evidence_package",
    "pricing",
    "tco",
    "decision",
    "market_scope",
    "model_review",
    "sales_artifact",
    "ui",
    "model_judge",
    "live_smoke",
}
DISABLED_FEATURES = {
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "hooks",
    "multi_agent",
    "memories",
    "browser_use",
    "computer_use",
    "in_app_browser",
    "code_mode",
    "code_mode_host",
    "image_generation",
    "view_image",
    "skill_search",
    "workspace_dependencies",
}
ISOLATED_DISABLED_FEATURES = DISABLED_FEATURES | {"goals", "sleep_tool", "tool_suggest"}
_ISOLATED_ENVIRONMENT_KEYS = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "CODEX_HOME",
    "HOME",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
}
INPUT_MARKER = "\nINPUT_JSON:\n"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = 256 * 1024 * 1024
# CLI 0.158.0, Windows, MAX, clean probe 03. Only bound paths/date/IDs are normalized.
# Original local-only capture SHA: 52e46183eb1a22d601a9a57a7dad9beda63c32a73c9b5bc1a3806fef45455f39.
# No native text, account IDs or authentication material is embedded here.
_CLEAN_NATIVE_PROFILE: dict[str, Any] = {
    "session": "98d33bbcc190520b82a2ea21cf62d862c0db61ea7fa4c169e545e95f6c3f3a94",
    "context": "8989857f08d19eda356edd0bc8adc7e0d135271a91f3e4a5dc2cc5db24e325b4",
    "world": "5f643dc50baa96afc4b937ce0687ffdff85b48cd43ae8ef105b4f31862e50746",
    "developers": [
        {
            "texts": [
                "4103287cd2f8e02c0c606bbbae018671bd04d7e7eeca9cbf862f8b53f9275313",
                "bec8e7b5358a20b4cd552dae768b3a65ebf4ea9fb2645220085b84d60ee3fe81",
            ],
            "kinds": "b67fe53c992a18abf65d6a9e1915f311584d5419dcb5cd26d2c578aa8def01b2",
            "envelope": "ac7f36a47810ac5098e8a4396f803c1132c0811239cdbc4d5bb83fdc6019fdd0",
        },
        {
            "texts": ["47091490938505958b0c22ff42db6fd79b272a2af6923166f4c2cc53c4fe0df4"],
            "kinds": "b6605479c666ba7cbf2116c3169490319fb3f27735b86993b1e30b3cfa75d61c",
        },
        {
            "texts": ["6ded806e3cdbb35599ecaf8742574bc5274908472b1729090010c404c2151e8e"],
            "kinds": "21a43fa62f8d5633517fa32dec424338a4db69b8d2d9cf53416f9b81754d320e",
        },
    ],
    "environment": {
        "text": "450c82cc9aacb917aa566ebccdd193e524174a08e0649a6182266fa9cd2bf650",
        "kinds": "80e1cc1b5f3c955063a4823df2e27939071c2048733752ba6720c2f1e24864fb",
    },
    "prompt": {
        "kinds": "998735cbe5844b560816eca39213b7631c08dd53ce35ab8c4816d31c8ebd85a6",
        "envelope": "2f2980d664ee6dc1b5606692a6384f21e98ab1b424400cbf91a874904220763e",
    },
    "envelope_metadata": {
        "developer": "ac7f36a47810ac5098e8a4396f803c1132c0811239cdbc4d5bb83fdc6019fdd0",
        "user": "2f2980d664ee6dc1b5606692a6384f21e98ab1b424400cbf91a874904220763e",
        "assistant": "0c1575ead47579318574a5ee893b02e9b25b3eb43cc2c324496313596fe03d6c",
    },
    # Observed local capture 8902234b454812b8452868c64c625fbff1cfbc362660fb61a2155a0cd4034b02.
    # These are distinct fingerprints, not normalization of the completeness flag.
    "retained_false_metadata": {
        "user": "679d39371ee0bfedaf56e9beaa3e8abfcca765a22d22875a1ce55d8c33b72e9b",
        "assistant": "e481a6b4bc87b48b06314277c71695f38f96e909a3e5beac4822c16a3cd9c777",
    },
    "assistant_output": {
        "keys": [
            "content",
            "id",
            "internal_chat_message_metadata_passthrough",
            "phase",
            "role",
            "type",
        ],
        "kinds": "a69f50eee46e418afc253e05b3768b9e53f8c2beb44287e16aea3f2de18b700f",
        "phase": "c2259d492611627a36a6d28028c7dbf1e55f4c2c4e4e39a84a74cdf987bfcb37",
    },
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FileRef(StrictModel):
    path: Text
    sha256: SHA256


class Scope(StrictModel):
    mode: Literal["release_candidate"]
    audience: Literal["internal_only"]
    production_apply_allowed: bool
    customer_output_allowed: bool


class Disclosures(StrictModel):
    alias_may_change: bool
    model_reexecution_nondeterministic: bool
    immutable_snapshot_claimed: bool
    preserved_record_replay_only: bool


class ReleaseBinding(StrictModel):
    release_id: Text
    frozen_at: Text
    data_cutoff: Text
    model_id: Literal["gpt-6-astra"]
    model_version: Literal["alias_unresolved"]
    artifact_fingerprint: SHA256


class EvidenceArtifact(StrictModel):
    evidence_id: Positive
    source_document_id: Positive
    snapshot: FileRef


class RuntimeIdentityEvidence(StrictModel):
    trace: FileRef
    capture: FileRef


class RuntimeCaptureProvenance(StrictModel):
    """Trusted collector receipt, bound to native bytes, not requested model flags."""

    schema_version: Literal["codex_runtime_session_capture.v1"]
    source_format: Literal["codex_session_jsonl"]
    audit_id: UUIDText
    session_id: UUIDText
    turn_id: UUIDText
    source_basename: Text
    cli_version: Text
    captured_at: Text
    trace_sha256: SHA256


class StageArtifacts(StrictModel):
    template: FileRef
    prompt: FileRef
    output_schema: FileRef = Field(alias="schema")
    response: FileRef
    execution: FileRef
    trace: FileRef
    stderr: FileRef
    runtime_identity: RuntimeIdentityEvidence | None = None


class Stages(StrictModel):
    primary: StageArtifacts
    adversarial: StageArtifacts
    arbitration: StageArtifacts | None


class AuditBundle(StrictModel):
    schema_version: Literal["internal_rc_audit_bundle.v1"]
    data_classification: Literal["official_public", "synthetic"]
    policy: FileRef
    scope: Scope
    disclosures: Disclosures
    release: ReleaseBinding
    code: FileRef
    rules: FileRef
    data: FileRef
    input: FileRef
    subject: FileRef
    subject_hash: SHA256
    evidence: Annotated[list[EvidenceArtifact], Field(min_length=1, max_length=128)]
    stages: Stages
    evaluation_plan: FileRef
    evaluation: FileRef


class RuntimeIsolation(StrictModel):
    """Trusted launcher assertions, cross-checked against the complete native trace."""

    schema_version: Literal["isolated_review_runtime.v1"]
    home: Text
    fresh_home: bool
    sanitized_environment: bool
    private_permissions: bool
    credential_copy_only: bool
    environment_keys: list[Text]


class ExecutionMetadata(StrictModel):
    """Collector receipt; actual_model_id is cross-checked against raw trace."""

    stage: StageName
    model_id: Literal["gpt-6-astra"]
    actual_model_id: Literal["gpt-6-astra"]
    model_provider: Literal["openai"]
    model_version: Literal["alias_unresolved"]
    fallback_used: bool
    prompt_version: Text
    prompt_sha256: SHA256
    schema_sha256: SHA256
    input_fingerprint: SHA256
    audit_id: UUIDText
    session_id: UUIDText
    response_id: Text
    started_at: Text
    completed_at: Text
    status: Literal["completed"]
    argv: Annotated[list[str], Field(min_length=1)]
    argv_sha256: SHA256
    reasoning_effort: Literal["max"]
    cwd: Text
    cwd_isolated: bool
    user_config_ignored: bool
    schema_path: Text
    response_path: Text
    exit_code: int
    stdout_sha256: SHA256
    stderr_sha256: SHA256
    response_sha256: SHA256
    runtime_isolation: RuntimeIsolation | None = None


class EvalCase(StrictModel):
    case_code: Text
    category: Text
    severity: Literal["critical", "high", "medium", "low"]


class EvaluationPlan(StrictModel):
    suite_code: Text
    suite_version: Text
    cases: Annotated[list[EvalCase], Field(min_length=1)]


class EvalCaseResult(EvalCase):
    passed: bool
    expected: Any
    actual: Any
    error: str | None


class EvaluationResult(StrictModel):
    schema_version: Literal["internal_rc_evaluation.v1"]
    run_id: Text
    release_id: Text
    artifact_fingerprint: SHA256
    model_identity_sha256: SHA256
    suite_code: Text
    suite_version: Text
    started_at: Text
    completed_at: Text
    status: Literal["succeeded"]
    full_chain_coverage: bool
    model_judge_executed: bool
    coverage_gaps: list[str]
    case_count: Positive
    passed: Positive
    failed: int
    skipped: int
    critical_failures: list[str]
    results: Annotated[list[EvalCaseResult], Field(min_length=1)]


class BundleError(ValueError):
    """Literal error codes only; never echo packet contents or model output."""


def _require(condition: object, code: str) -> None:
    if not condition:
        raise BundleError(code)


def object_sha256(value: object) -> str:
    """Panel-compatible JSON fingerprint, not a file-byte hash."""
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def compute_artifact_fingerprint(manifest: AuditBundle | dict[str, Any]) -> str:
    """Build the pre-eval binding; does NOT validate or approve a bundle.

    Builders may omit release.artifact_fingerprint and evaluation while hashing.
    Everything else, including all review artifacts, is included to prevent
    changing a review or its evidence while reusing a successful evaluation.
    """
    raw = (
        manifest.model_dump(by_alias=True, exclude_unset=True)
        if isinstance(manifest, AuditBundle)
        else dict(manifest)
    )
    raw.pop("evaluation", None)
    release = dict(raw["release"])
    release.pop("artifact_fingerprint", None)
    raw["release"] = release
    return object_sha256(raw)


def actual_model_identity_sha256(executions: dict[str, ExecutionMetadata]) -> str:
    """Bind Eval to the actual, isolated review executions, not just the alias."""
    return object_sha256(
        {
            stage: {
                key: getattr(meta, key)
                for key in (
                    "actual_model_id",
                    "model_provider",
                    "model_version",
                    "session_id",
                    "response_id",
                    "audit_id",
                    "stdout_sha256",
                    "response_sha256",
                )
            }
            for stage, meta in executions.items()
        }
    )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise BundleError("non_finite_json")


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise BundleError("json_object_required")
    result: dict[str, Any] = value
    return result


def _time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    _require(stamp.tzinfo is not None and stamp.utcoffset() is not None, "timezone_required")
    return stamp.astimezone(UTC)


class _Reader:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        _require(self.root.is_dir(), "audit_directory_required")
        self.files: dict[Path, bytes] = {}
        self.total = 0

    def path(self, name: str) -> Path:
        _require(isinstance(name, str), "unsafe_artifact_path")
        parts = name.split("/")
        _require(
            bool(name)
            and "\\" not in name
            and ":" not in name
            and not PurePosixPath(name).is_absolute()
            and not PureWindowsPath(name).drive
            and all(
                part not in {"", ".", ".."} and part == part.strip() and not part.endswith(".")
                for part in parts
            )
            and not any(ord(char) < 32 for char in name),
            "unsafe_artifact_path",
        )
        # Reject even in-root symlinks/junctions: a sealed bundle uses regular files.
        path = self.root
        for part in parts:
            path /= part
            # FILE_ATTRIBUTE_REPARSE_POINT also covers Windows junctions on Python 3.11.
            reparse = getattr(path.lstat(), "st_file_attributes", 0) & 0x400
            _require(not path.is_symlink() and not reparse, "linked_artifact_path")
        resolved = path.resolve(strict=True)
        _require(
            resolved.is_relative_to(self.root) and resolved.is_file(), "artifact_outside_audit"
        )
        _require(resolved.stat().st_nlink == 1, "hardlinked_artifact")
        return resolved

    def read(self, name: str, digest: str | None = None) -> bytes:
        path = self.path(name)
        if path not in self.files:
            _require(path.stat().st_size <= MAX_FILE_BYTES, "artifact_too_large")
            with path.open("rb") as handle:
                raw = handle.read(MAX_FILE_BYTES + 1)
            _require(len(raw) <= MAX_FILE_BYTES, "artifact_too_large")
            self.total += len(raw)
            _require(self.total <= MAX_BUNDLE_BYTES, "bundle_too_large")
            self.files[path] = raw
        raw = self.files[path]
        if digest is not None:
            _require(sha256(raw).hexdigest() == digest, "artifact_hash_mismatch")
        return raw

    def ref(self, ref: FileRef) -> bytes:
        return self.read(ref.path, ref.sha256)

    def unchanged(self) -> None:
        # Best-effort concurrent-mutation check; consumption still requires a sealed directory.
        for path, raw in self.files.items():
            checked = self.path(path.relative_to(self.root).as_posix())
            with checked.open("rb") as handle:
                current = handle.read(MAX_FILE_BYTES + 1)
            _require(current == raw, "artifact_changed_during_validation")


def _policy(raw: bytes) -> None:
    policy = yaml.safe_load(raw.decode("utf-8"))
    _require(isinstance(policy, dict), "policy_invalid")
    _require(policy.get("policy_version") == "internal_rc_audit_bundle_v1", "policy_version")
    _require(
        policy.get("authorization")
        == {
            "authorized_by": "project_owner",
            "recorded_on": "2026-09-30",
            "source": "explicit_in_thread_answer",
            "decision": "allow_internal_release_candidate_audit_alternative",
        },
        "owner_authorization_missing",
    )
    _require(
        object_sha256(policy.get("deployment_scope"))
        == object_sha256(
            {
                "allowed_mode": "release_candidate",
                "audience": "internal_only",
                "production_apply_allowed": False,
            }
        ),
        "policy_scope_invalid",
    )
    _require(
        object_sha256(policy.get("model"))
        == object_sha256(
            {
                "required_id": MODEL_ID,
                "immutable_snapshot_claimed": False,
                "allow_weaker_fallback": False,
            }
        ),
        "policy_model_invalid",
    )
    controls = policy.get("required_controls")
    _require(
        isinstance(controls, list)
        and all(isinstance(c, str) for c in controls)
        and set(controls) == REQUIRED_CONTROLS,
        "policy_controls_invalid",
    )
    _require(
        object_sha256(policy.get("gate_semantics"))
        == object_sha256(
            {
                "owner_authorization_alone_passes": False,
                "audit_bundle_must_be_verified": True,
                "critical_eval_failure_allowed": False,
                "original_fact_price_and_review_thresholds_unchanged": True,
            }
        ),
        "policy_gate_semantics_invalid",
    )


def _scope(bundle: AuditBundle, allow_synthetic: bool) -> None:
    _require(
        not bundle.scope.production_apply_allowed and not bundle.scope.customer_output_allowed,
        "internal_rc_only",
    )
    disclosure = bundle.disclosures
    _require(
        disclosure.alias_may_change
        and disclosure.model_reexecution_nondeterministic
        and disclosure.preserved_record_replay_only
        and not disclosure.immutable_snapshot_claimed,
        "alias_drift_not_disclosed",
    )
    _require(
        bundle.data_classification != "synthetic" or allow_synthetic,
        "synthetic_cannot_authorize_release",
    )


def _no_prior_context(value: object) -> None:
    forbidden = {
        "independent_opinions",
        "primary_opinion",
        "adversarial_opinion",
        "prior_messages",
        "conversation_history",
        "generator_reasoning",
        "hidden_reasoning",
        "previous_response_id",
    }
    if isinstance(value, dict):
        _require(not (forbidden & value.keys()), "cross_stage_context_contamination")
        for child in value.values():
            _no_prior_context(child)
    elif isinstance(value, list):
        for child in value:
            _no_prior_context(child)


def _packet(reader: _Reader, bundle: AuditBundle) -> dict[str, Any]:
    payload = _json(reader.ref(bundle.input))
    subject = _json(reader.ref(bundle.subject))
    _require(
        object_sha256(subject) == bundle.subject_hash == payload.get("input_fingerprint"),
        "subject_hash_mismatch",
    )
    without_fingerprint = {k: v for k, v in payload.items() if k != "input_fingerprint"}
    _require(
        subject.get("public_payload_sha256") == object_sha256(without_fingerprint),
        "frozen_packet_mismatch",
    )
    _require(
        set(subject)
        == {"records", "mapping_approval_sha256", "implementation", "public_payload_sha256"},
        "subject_manifest_invalid",
    )
    _require(isinstance(subject["records"], list) and subject["records"], "subject_records_missing")
    seen: set[tuple[str, int]] = set()
    for record in subject["records"]:
        _require(
            isinstance(record, dict) and set(record) == {"table", "id", "sha256"},
            "subject_record_invalid",
        )
        _require(
            isinstance(record["table"], str)
            and record["table"]
            and type(record["id"]) is int
            and record["id"] > 0
            and _digest(record["sha256"]),
            "subject_record_invalid",
        )
        key = record["table"], record["id"]
        _require(key not in seen, "duplicate_subject_record")
        seen.add(key)
    implementation = subject["implementation"]
    _require(
        isinstance(implementation, dict)
        and implementation
        and all(_digest(d) for d in implementation.values())
        and _digest(subject["mapping_approval_sha256"]),
        "subject_implementation_invalid",
    )
    _require(
        payload.get("data_classification") == bundle.data_classification
        and payload.get("target_type") == "candidate_decision_result"
        and payload.get("precheck") == "passed"
        and payload.get("authorization_scope") == "public_evidence_internal_report_only"
        and type(payload.get("target_id")) is int
        and payload["target_id"] > 0
        and isinstance(payload.get("prompt_version"), str)
        and payload["prompt_version"],
        "frozen_packet_scope_invalid",
    )
    _require(
        isinstance(payload.get("subject"), dict)
        and type(payload["subject"].get("id")) is int
        and payload["subject"]["id"] == payload["target_id"],
        "packet_target_mismatch",
    )
    _no_prior_context(payload)
    items = payload.get("evidence")
    if not isinstance(items, list) or len(items) != len(bundle.evidence):
        raise BundleError("evidence_set_mismatch")
    by_id: dict[int, dict[str, Any]] = {}
    for item in items:
        _require(
            isinstance(item, dict)
            and type(item.get("evidence_id")) is int
            and item["evidence_id"] > 0
            and item["evidence_id"] not in by_id,
            "evidence_id_invalid",
        )
        by_id[item["evidence_id"]] = item
    _require(
        len({e.evidence_id for e in bundle.evidence}) == len(bundle.evidence),
        "duplicate_evidence_id",
    )
    for evidence in bundle.evidence:
        item = by_id.get(evidence.evidence_id, {})
        _require(
            type(item.get("source_document_id")) is int
            and item["source_document_id"] == evidence.source_document_id
            and item.get("source_sha256") == evidence.snapshot.sha256,
            "evidence_source_mismatch",
        )
        reader.ref(evidence.snapshot)
        excerpt = item.get("excerpt")
        _require(
            isinstance(excerpt, str)
            and excerpt
            and sha256(excerpt.encode("utf-8")).hexdigest() == item.get("excerpt_sha256"),
            "evidence_excerpt_mismatch",
        )
        _require(
            _time(item["captured_at"]) <= _time(bundle.release.data_cutoff), "evidence_after_cutoff"
        )
    return payload


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _isolation(meta: ExecutionMetadata) -> RuntimeIsolation:
    isolation = meta.runtime_isolation
    _require(isolation is not None, "runtime_isolation_required")
    assert isolation is not None
    _require(
        isolation.fresh_home is True
        and isolation.sanitized_environment is True
        and isolation.private_permissions is True
        and isolation.credential_copy_only is True,
        "runtime_isolation_attestation_invalid",
    )
    keys = [key.upper() for key in isolation.environment_keys]
    _require(
        len(keys) == len(set(keys))
        and set(keys) <= _ISOLATED_ENVIRONMENT_KEYS
        and "CODEX_HOME" in keys,
        "runtime_environment_not_isolated",
    )
    path_type = PureWindowsPath if PureWindowsPath(meta.cwd).drive else PurePosixPath
    cwd, home = path_type(meta.cwd), path_type(isolation.home)
    _require(
        cwd.is_absolute()
        and home.is_absolute()
        and cwd.name == "work"
        and home.name == "home"
        and cwd.parent == home.parent
        and not any(part in {".", ".."} for part in isolation.home.replace("\\", "/").split("/")),
        "runtime_home_binding_invalid",
    )
    return isolation


def _argv(
    meta: ExecutionMetadata, *, has_runtime_identity: bool = False, require_isolation: bool = False
) -> None:
    _require(
        not require_isolation or meta.runtime_isolation is not None, "runtime_isolation_required"
    )
    ephemeral = "--ephemeral" in meta.argv
    _require(ephemeral or has_runtime_identity, "execution_session_capture_required")
    if meta.runtime_isolation is not None:
        from cloud_expert.model_review.isolated_runtime import isolated_config_args

        isolation = _isolation(meta)
        _require(has_runtime_identity and not ephemeral, "runtime_isolated_capture_required")
        expected = [
            meta.argv[0],
            "exec",
            "-m",
            MODEL_ID,
            "-c",
            'model_reasoning_effort="max"',
            *isolated_config_args(Path(isolation.home)),
            "--output-schema",
            meta.schema_path,
            "-o",
            meta.response_path,
            "-",
        ]
        _require(meta.argv == expected, "execution_argv_unsafe")
    else:
        _legacy_argv(meta, ephemeral)
    _require(object_sha256(meta.argv) == meta.argv_sha256, "execution_argv_hash_mismatch")
    path_type = PureWindowsPath if PureWindowsPath(meta.cwd).drive else PurePosixPath
    cwd = path_type(meta.cwd)
    _require(
        cwd.is_absolute()
        and not any(part in {".", ".."} for part in meta.cwd.replace("\\", "/").split("/"))
        and path_type(meta.schema_path).parent == cwd
        and path_type(meta.response_path).parent == cwd
        and meta.schema_path != meta.response_path,
        "execution_cwd_not_isolated",
    )


def _legacy_argv(meta: ExecutionMetadata, ephemeral: bool) -> None:
    prefix = [
        meta.argv[0],
        "exec",
        "--ignore-user-config",
        "--strict-config",
        "-m",
        MODEL_ID,
        "-c",
        'model_reasoning_effort="max"',
        "-c",
        'model_provider="openai"',
        "-c",
        "project_doc_max_bytes=0",
        "-c",
        'web_search="disabled"',
        *(["--ephemeral"] if ephemeral else []),
        "-s",
        "read-only",
        "--skip-git-repo-check",
        "--json",
        "--output-schema",
        meta.schema_path,
        "-o",
        meta.response_path,
    ]
    _require(meta.argv[: len(prefix)] == prefix and meta.argv[-1] == "-", "execution_argv_unsafe")
    tail = meta.argv[len(prefix) : -1]
    _require(
        len(tail) == 2 * len(DISABLED_FEATURES)
        and all(flag == "--disable" for flag in tail[::2])
        and set(tail[1::2]) == DISABLED_FEATURES,
        "execution_features_not_isolated",
    )


def validate_review_cli_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate a single tool-free turn; return a view without the exact startup notice.

    Captured stdout must remain unchanged for hashing and audit provenance.
    This does not attest runtime identity or bind the final response to an artifact.
    """
    startup_notice = {
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
    _require(all(isinstance(event, dict) for event in events), "trace_unknown_or_reused_turn")
    has_notice = len(events) > 1 and events[1] == startup_notice
    events = events[:1] + events[2:] if has_notice else list(events)
    _require(len(events) >= 4, "execution_trace_incomplete")
    _require(events[0].get("type") == "thread.started", "trace_session_mismatch")
    _require(events[1].get("type") == "turn.started", "trace_unknown_or_reused_turn")
    _require(events[-1].get("type") == "turn.completed", "execution_trace_incomplete")
    final_messages: list[dict[str, Any]] = []

    def check_metadata(value: object) -> None:
        if isinstance(value, dict):
            _require(
                not value.get("error")
                and ("fallback_used" not in value or value["fallback_used"] is False)
                and not value.get("previous_response_id")
                and not value.get("resumed_from")
                and not value.get("parent_thread_id")
                and value.get("status") not in {"failed", "cancelled", "incomplete"},
                "trace_failure_or_context_reuse",
            )
            for field in ("model", "model_id", "actual_model_id"):
                _require(field not in value or value[field] == MODEL_ID, "trace_model_mismatch")
            _require(
                "model_provider" not in value or value["model_provider"] == "openai",
                "trace_provider_mismatch",
            )
            for child in value.values():
                check_metadata(child)
        elif isinstance(value, list):
            for child in value:
                check_metadata(child)

    check_metadata(events)
    for event in events[2:-1]:
        _require(
            event.get("type") in {"item.started", "item.updated", "item.completed"},
            "trace_unknown_or_reused_turn",
        )
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") not in {"agent_message", "reasoning"}:
            raise BundleError("trace_tool_or_unknown_item")
        _require(not has_notice or item.get("id") != "item_0", "trace_tool_or_unknown_item")
        if item["type"] == "agent_message" and event["type"] == "item.completed":
            final_messages.append(item)
    _require(len(final_messages) == 1, "full_response_not_attested")
    return events


def _trace(
    raw: bytes,
    response: bytes,
    meta: ExecutionMetadata,
    *,
    runtime_identity_verified: bool = False,
) -> None:
    events = validate_review_cli_events([_json(line) for line in raw.splitlines() if line.strip()])
    _require(events[0].get("thread_id") == meta.session_id, "trace_session_mismatch")
    _require(
        runtime_identity_verified
        or (
            events[1].get("model") == meta.actual_model_id
            and events[1].get("model_provider") == meta.model_provider
        ),
        "actual_model_identity_unverified",
    )
    final_messages = [
        event["item"]
        for event in events[2:-1]
        if event["type"] == "item.completed" and event["item"]["type"] == "agent_message"
    ]
    _require(
        len(final_messages) == 1
        and final_messages[0].get("id") == meta.response_id
        and isinstance(final_messages[0].get("text"), str)
        and final_messages[0]["text"].strip() == response.decode("utf-8").strip(),
        "full_response_not_attested",
    )


def _native_envelope_metadata(
    event: dict[str, Any], capture: RuntimeCaptureProvenance
) -> str | None:
    if "metadata" not in event:
        return None
    payload = event["payload"]
    _require(
        event["type"] == "response_item" and payload.get("type") == "message",
        "runtime_clean_envelope_invalid",
    )
    metadata = deepcopy(event["metadata"])
    _require(isinstance(metadata, dict), "runtime_clean_envelope_invalid")
    retained = metadata.get("retained_source")
    if retained is not None:
        _require(
            isinstance(retained, dict)
            and set(retained) == {"id", "revision", "complete"}
            and type(retained["complete"]) is bool
            and isinstance(payload.get("id"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", payload["id"])
            and retained["id"]
            == {
                "message_id": payload.get("id"),
                "turn_id": capture.turn_id,
                "role": payload.get("role"),
            }
            and isinstance(retained["revision"], str)
            and re.fullmatch(
                r"[a-z]{8}_[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", retained["revision"]
            ),
            "runtime_retained_source_invalid",
        )
        retained["id"]["message_id"] = "{MESSAGE}"
        retained["id"]["turn_id"] = "{TURN}"
        retained["revision"] = retained["revision"][:9] + "{REVISION}"
    fingerprint = object_sha256(metadata)
    profile_key = (
        "retained_false_metadata"
        if retained is not None and retained["complete"] is False
        else "envelope_metadata"
    )
    _require(
        fingerprint == _CLEAN_NATIVE_PROFILE.get(profile_key, {}).get(payload.get("role")),
        "runtime_clean_envelope_invalid",
    )
    return fingerprint


def _clean_native_inputs(
    events: list[dict[str, Any]],
    meta: ExecutionMetadata,
    capture: RuntimeCaptureProvenance,
    prompt: str,
) -> int:
    """Bind the complete generated input prefix to one version-pinned clean profile."""
    _isolation(meta)
    _require(bool(_CLEAN_NATIVE_PROFILE), "runtime_clean_profile_unavailable")
    previous_ordinal = -1
    for event in events:
        _require(
            set(event)
            in (
                {"timestamp", "ordinal", "type", "payload"},
                {"timestamp", "ordinal", "type", "payload", "metadata"},
            )
            and isinstance(event["timestamp"], str)
            and isinstance(event["type"], str)
            and isinstance(event["payload"], dict)
            and type(event["ordinal"]) is int
            and event["ordinal"] > previous_ordinal,
            "runtime_clean_envelope_invalid",
        )
        previous_ordinal = event["ordinal"]
        _native_envelope_metadata(event, capture)
    developers = _CLEAN_NATIVE_PROFILE["developers"]
    env_index = 2 + len(developers)
    world_index, context_index, prompt_index = env_index + 1, env_index + 2, env_index + 3
    kinds = ["session_meta", "event_msg"] + ["response_item"] * (len(developers) + 1)
    kinds += ["world_state", "turn_context", "response_item"]
    _require(
        len(events) > prompt_index
        and [e.get("type") for e in events[: prompt_index + 1]] == kinds
        and sum(e.get("type") == "world_state" for e in events) == 1
        and sum(e.get("type") == "turn_context" for e in events) == 1,
        "runtime_clean_input_order_invalid",
    )
    session = deepcopy(events[0]["payload"])
    context = deepcopy(events[context_index]["payload"])
    world = deepcopy(events[world_index]["payload"])
    _require(
        isinstance(session, dict) and isinstance(context, dict) and isinstance(world, dict),
        "runtime_event_payload_invalid",
    )
    for key in ("creator_user_id", "creator_account_id"):
        value = session.get(key)
        _require(
            isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value),
            "runtime_local_auth_metadata_invalid",
        )
        session[key] = "{LOCAL_AUTH_METADATA}"
    for key in ("id", "session_id"):
        _require(session.get(key) == meta.session_id, "runtime_session_mismatch")
        session[key] = "{SESSION}"
    _require(
        _time(meta.started_at) <= _time(session["timestamp"]) <= _time(meta.completed_at),
        "runtime_event_time_invalid",
    )
    session["timestamp"] = "{TIMESTAMP}"
    _require(
        session.get("cwd") == meta.cwd and session.get("runtime_workspace_roots") == [meta.cwd],
        "runtime_home_binding_invalid",
    )
    session.update(cwd="{CWD}", runtime_workspace_roots=["{CWD}"])
    window = session.get("context_window")
    _require(
        isinstance(window, dict)
        and set(window) == {"window_id"}
        and isinstance(window["window_id"], str)
        and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", window["window_id"]),
        "runtime_clean_session_invalid",
    )
    session["context_window"] = {"window_id": "{WINDOW}"}
    _require(
        object_sha256(session) == _CLEAN_NATIVE_PROFILE["session"], "runtime_clean_session_invalid"
    )

    for key in ("turn_id", "root_turn_id"):
        _require(context.get(key) == capture.turn_id, "runtime_identity_or_turn_mismatch")
        context[key] = "{TURN}"
    _require(
        context.get("cwd") == meta.cwd
        and context.get("workspace_roots") == [meta.cwd]
        and context.get("model") == MODEL_ID
        and context.get("effort") == "max",
        "runtime_model_identity_unverified",
    )
    date, timezone = context.get("current_date"), context.get("timezone")
    _require(isinstance(date, str) and isinstance(timezone, str), "runtime_environment_invalid")
    try:
        local_date = _time(events[context_index]["timestamp"]).astimezone(ZoneInfo(timezone)).date()
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise BundleError("runtime_environment_invalid") from exc
    _require(date == local_date.isoformat(), "runtime_environment_date_mismatch")
    context.update(cwd="{CWD}", workspace_roots=["{CWD}"], current_date="{DATE}")
    _require(
        object_sha256(context) == _CLEAN_NATIVE_PROFILE["context"], "runtime_clean_context_invalid"
    )
    state = world.get("state")
    _require(isinstance(state, dict) and world.get("full") is True, "runtime_clean_world_invalid")
    _require(
        state.get("permissions", {}).get("approved_command_prefixes") == []
        and state.get("agents_md") == {}
        and state.get("managed_developer_instructions") == {}
        and state.get("persistent_mode") == {},
        "runtime_inherited_context",
    )
    skill_state = state.get("host_skills")
    _require(
        skill_state in (None, {})
        or isinstance(skill_state, dict)
        and skill_state.get("body", "") == "",
        "runtime_inherited_skills",
    )
    environments = state.get("environments", {})
    local = environments.get("environments", {}).get("local", {})
    _require(
        local.get("cwd") == meta.cwd
        and environments.get("current_date") == date
        and environments.get("timezone") == timezone,
        "runtime_environment_binding_invalid",
    )
    filesystem = environments.get("filesystem")
    _require(isinstance(filesystem, str), "runtime_environment_invalid")

    def normalize(text: str) -> str:
        _require(
            all(marker not in text for marker in ("{CWD}", "{DATE}")),
            "runtime_generated_message_invalid",
        )
        return text.replace(meta.cwd, "{CWD}").replace(date, "{DATE}")

    local["cwd"] = "{CWD}"
    environments["current_date"] = "{DATE}"
    environments["filesystem"] = normalize(filesystem)
    _require(object_sha256(world) == _CLEAN_NATIVE_PROFILE["world"], "runtime_clean_world_invalid")
    message_ids: set[str] = set()
    user_items = 0
    for index, event in enumerate(events):
        payload = event.get("payload", {})
        if event.get("type") == "event_msg":
            _require(
                payload.get("type")
                in {"task_started", "task_complete", "token_count", "item_completed"},
                "runtime_unknown_event",
            )
            item = payload.get("item", {})
            if payload.get("type") == "item_completed" and item.get("type") == "UserMessage":
                user_items += 1
                _require(
                    index > prompt_index
                    and user_items == 1
                    and set(item) == {"type", "id", "content"}
                    and isinstance(item["id"], str)
                    and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", item["id"])
                    and item["content"] == [{"type": "text", "text": prompt, "text_elements": []}],
                    "runtime_input_or_prior_context_mismatch",
                )
        if event.get("type") == "response_item" and payload.get("type") == "reasoning":
            _require(
                index > prompt_index
                and set(payload)
                == {
                    "type",
                    "id",
                    "summary",
                    "encrypted_content",
                    "internal_chat_message_metadata_passthrough",
                }
                and isinstance(payload["id"], str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", payload["id"])
                and isinstance(payload["summary"], list)
                and isinstance(payload["encrypted_content"], str)
                and payload["internal_chat_message_metadata_passthrough"]
                == {"turn_id": capture.turn_id},
                "runtime_output_metadata_invalid",
            )
        if event.get("type") != "response_item" or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role == "assistant":
            _require(index > prompt_index, "runtime_prior_assistant_context")
            output = _CLEAN_NATIVE_PROFILE["assistant_output"]
            metadata = payload.get("internal_chat_message_metadata_passthrough")
            _require(
                sorted(payload) == output["keys"]
                and object_sha256(payload.get("phase")) == output["phase"]
                and isinstance(metadata, dict)
                and set(metadata) == {"turn_id", "create_time", "content_item_kinds"}
                and metadata["turn_id"] == capture.turn_id
                and type(metadata["create_time"]) in (int, float)
                # Observed assistant creation metadata predates the local session;
                # only native envelope timestamps attest the execution window.
                and math.isfinite(metadata["create_time"])
                and metadata["create_time"] > 0
                and object_sha256(metadata["content_item_kinds"]) == output["kinds"],
                "runtime_output_metadata_invalid",
            )
            continue
        _require(index in [*range(2, env_index), env_index, prompt_index], "runtime_extra_input")
        _require(
            set(payload)
            == {"type", "role", "id", "content", "internal_chat_message_metadata_passthrough"}
            and role == ("developer" if index < env_index else "user"),
            "runtime_generated_message_invalid",
        )
        message_id = payload.get("id")
        _require(
            isinstance(message_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", message_id)
            and message_id not in message_ids,
            "runtime_input_identity_invalid",
        )
        message_ids.add(message_id)
        metadata = payload["internal_chat_message_metadata_passthrough"]
        _require(
            isinstance(metadata, dict)
            and set(metadata) == {"turn_id", "create_time", "content_item_kinds"}
            and metadata["turn_id"] == capture.turn_id
            and type(metadata["create_time"]) in (int, float)
            and _time(meta.started_at).timestamp()
            <= metadata["create_time"]
            <= _time(meta.completed_at).timestamp(),
            "runtime_input_metadata_invalid",
        )
        content = payload.get("content")
        _require(
            isinstance(content, list)
            and content
            and (index < env_index or len(content) == 1)
            and all(
                isinstance(part, dict)
                and set(part) == {"type", "text"}
                and part["type"] == "input_text"
                and isinstance(part["text"], str)
                for part in content
            ),
            "runtime_generated_message_invalid",
        )
        text = content[0]["text"]
        if index < env_index:
            expected = developers[index - 2]
            _require(
                [sha256(part["text"].encode()).hexdigest() for part in content]
                == expected["texts"],
                "runtime_developer_text_invalid",
            )
        elif index == env_index:
            expected = _CLEAN_NATIVE_PROFILE["environment"]
            _require(
                filesystem in text
                and "<!" not in text
                and "<?" not in text
                and sha256(normalize(text).encode()).hexdigest() == expected["text"],
                "runtime_generated_environment_invalid",
            )
        else:
            expected = _CLEAN_NATIVE_PROFILE["prompt"]
            _require(text == prompt, "runtime_input_or_prior_context_mismatch")
        _require(
            object_sha256(metadata["content_item_kinds"]) == expected["kinds"],
            "runtime_input_metadata_invalid",
        )
        expected_envelope = expected.get("envelope")
        if (
            index == prompt_index
            and event.get("metadata", {}).get("retained_source", {}).get("complete") is False
        ):
            expected_envelope = _CLEAN_NATIVE_PROFILE.get("retained_false_metadata", {}).get("user")
        _require(
            _native_envelope_metadata(event, capture) == expected_envelope,
            "runtime_clean_envelope_invalid",
        )
    _require(user_items == 1, "runtime_input_missing")
    # Only the two observed pairs are supported; neither flag proves text completeness.
    retained_states = [
        (event["payload"].get("role"), event["metadata"]["retained_source"]["complete"])
        for event in events
        if "retained_source" in event.get("metadata", {})
    ]
    _require(
        retained_states
        in ([("user", True), ("assistant", True)], [("user", False), ("assistant", False)]),
        "runtime_retained_source_invalid",
    )
    return env_index


def _runtime_identity(
    reader: _Reader,
    evidence: RuntimeIdentityEvidence,
    meta: ExecutionMetadata,
    prompt: str,
    response: bytes,
    frozen_at: str,
    *,
    require_isolation: bool = False,
) -> None:
    _require(
        not require_isolation or meta.runtime_isolation is not None, "runtime_isolation_required"
    )
    capture = RuntimeCaptureProvenance.model_validate(_json(reader.ref(evidence.capture)))
    _require(
        capture.audit_id == meta.audit_id
        and capture.session_id == meta.session_id
        and capture.trace_sha256 == evidence.trace.sha256,
        "runtime_capture_provenance_mismatch",
    )
    _require(
        capture.source_basename.startswith("rollout-")
        and capture.source_basename.endswith(f"-{meta.session_id}.jsonl")
        and not any(char in capture.source_basename for char in "/\\:\0"),
        "runtime_capture_source_invalid",
    )
    _require(
        _time(meta.completed_at) <= _time(capture.captured_at) <= _time(frozen_at),
        "runtime_capture_time_invalid",
    )
    events = [_json(line) for line in reader.ref(evidence.trace).splitlines() if line.strip()]
    _require(events and events[0].get("type") == "session_meta", "runtime_session_incomplete")
    env_index = None
    if meta.runtime_isolation is not None:
        _argv(meta, has_runtime_identity=True, require_isolation=True)
        _require(
            sha256(prompt.encode("utf-8")).hexdigest() == meta.prompt_sha256
            and sha256(response).hexdigest() == meta.response_sha256,
            "execution_artifact_hash_mismatch",
        )
        try:
            env_index = _clean_native_inputs(events, meta, capture, prompt)
        except (KeyError, TypeError, AttributeError) as exc:
            raise BundleError("runtime_clean_schema_invalid") from exc
    sessions: list[dict[str, Any]] = []
    contexts: list[dict[str, Any]] = []
    starts: list[dict[str, Any]] = []
    completions: list[dict[str, Any]] = []
    user_inputs: dict[str, list[str]] = {"response_item": [], "event_msg": []}
    final_responses: list[str] = []
    last_time = _time(meta.started_at)
    last_event = ""
    for event_index, event in enumerate(events):
        stamp = _time(event["timestamp"])
        _require(last_time <= stamp <= _time(meta.completed_at), "runtime_event_time_invalid")
        last_time = stamp
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise BundleError("runtime_event_payload_invalid")
        _require(
            not any(
                payload.get(key)
                for key in (
                    "parent_thread_id",
                    "forked_from_id",
                    "resumed_from",
                    "previous_response_id",
                )
            ),
            "runtime_inherited_context",
        )
        for key, expected in (
            ("thread_id", meta.session_id),
            ("turn_id", capture.turn_id),
            ("root_turn_id", capture.turn_id),
            ("model", meta.actual_model_id),
            ("model_provider", meta.model_provider),
        ):
            _require(
                key not in payload or payload[key] is None or payload[key] == expected,
                "runtime_identity_or_turn_mismatch",
            )
        _require(
            ("fallback_used" not in payload or payload["fallback_used"] is False)
            and not payload.get("error"),
            "runtime_failure_or_fallback",
        )
        kind = event["type"]
        last_event = kind
        if kind == "session_meta":
            sessions.append(payload)
            _require(
                len(sessions) == 1
                and payload.get("id") == meta.session_id
                and payload.get("model_provider") == meta.model_provider
                and payload.get("cli_version") == capture.cli_version
                and _same_cwd(payload.get("cwd"), meta.cwd),
                "runtime_session_mismatch",
            )
        elif kind == "turn_context":
            _require(len(starts) == 1 and not completions, "runtime_context_outside_turn")
            contexts.append(payload)
            _require(
                payload.get("turn_id") == capture.turn_id
                and payload.get("model") == meta.actual_model_id
                and payload.get("effort") == meta.reasoning_effort
                and _same_cwd(payload.get("cwd"), meta.cwd),
                "runtime_model_identity_unverified",
            )
        elif kind == "response_item":
            item_type = payload.get("type")
            _require(item_type in {"message", "reasoning"}, "runtime_tool_or_unknown_item")
            if item_type == "reasoning" or payload.get("role") == "assistant":
                _require(bool(contexts) and not completions, "runtime_prior_assistant_context")
            if item_type == "message":
                role = payload.get("role")
                _require(
                    role in {"system", "developer", "user", "assistant"},
                    "runtime_message_role_invalid",
                )
                if role in {"user", "assistant"}:
                    text = _runtime_message_text(payload)
                    if role == "user":
                        if event_index != env_index:
                            user_inputs["response_item"].append(text)
                    elif payload.get("channel") in {None, "final"}:
                        if env_index is not None:
                            _require(
                                payload["content"]
                                == [{"type": "output_text", "text": response.decode("utf-8")}],
                                "runtime_full_response_mismatch",
                            )
                        final_responses.append(text)
        elif kind == "event_msg":
            event_type = payload.get("type")
            last_event = str(event_type)
            if event_type == "task_started":
                starts.append(payload)
                _require(
                    len(starts) == 1
                    and not contexts
                    and not completions
                    and payload.get("turn_id") == capture.turn_id,
                    "runtime_multiple_turns",
                )
            elif event_type == "task_complete":
                completions.append(payload)
                _require(
                    len(starts) == 1
                    and contexts
                    and len(completions) == 1
                    and payload.get("turn_id") == capture.turn_id
                    and isinstance(payload.get("last_agent_message"), str)
                    and (
                        payload["last_agent_message"].encode("utf-8") == response
                        if env_index is not None
                        else payload["last_agent_message"].strip()
                        == response.decode("utf-8").strip()
                    ),
                    "runtime_completion_mismatch",
                )
            elif event_type == "user_message":
                _require(isinstance(payload.get("message"), str), "runtime_input_missing")
                user_inputs["event_msg"].append(payload["message"])
            elif event_type == "item_completed":
                item = payload.get("item")
                _require(
                    isinstance(item, dict)
                    and item.get("type")
                    in {
                        "UserMessage",
                        "AgentMessage",
                        "Reasoning",
                        "user_message",
                        "agent_message",
                        "reasoning",
                    },
                    "runtime_tool_or_unknown_item",
                )
            else:
                _require(
                    event_type in {"token_count", "agent_message", "agent_reasoning"},
                    "runtime_unknown_event",
                )
        elif kind == "world_state" and env_index is not None:
            _require(event_index == env_index + 1, "runtime_clean_input_order_invalid")
        elif kind == "token_usage_record":
            _require(bool(contexts) and not completions, "runtime_usage_outside_turn")
        else:
            # In particular, world_state/compacted events need a separately reviewed adapter.
            raise BundleError("runtime_unknown_event")
    _require(
        len(sessions) == len(starts) == len(completions) == 1
        and contexts
        and last_event == "task_complete",
        "runtime_session_incomplete",
    )
    _require(
        any(user_inputs.values())
        and all(len(inputs) <= 1 for inputs in user_inputs.values())
        and all(text == prompt for inputs in user_inputs.values() for text in inputs),
        "runtime_input_or_prior_context_mismatch",
    )
    _require(
        (len(final_responses) == 1 if env_index is not None else len(final_responses) <= 1)
        and all(
            text.encode("utf-8") == response
            if env_index is not None
            else text.strip() == response.decode("utf-8").strip()
            for text in final_responses
        ),
        "runtime_full_response_mismatch",
    )


def _same_cwd(value: object, expected: str) -> bool:
    if not isinstance(value, str):
        return False
    return (
        value.replace("\\", "/").rstrip("/").casefold()
        == expected.replace("\\", "/").rstrip("/").casefold()
    )


def _runtime_message_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list) or not content:
        raise BundleError("runtime_message_content_invalid")
    parts: list[str] = []
    for item in content:
        _require(
            isinstance(item, dict)
            and item.get("type") in {"input_text", "output_text"}
            and isinstance(item.get("text"), str),
            "runtime_message_content_invalid",
        )
        parts.append(item["text"])
    return "".join(parts)


def _stage(
    reader: _Reader,
    name: str,
    refs: StageArtifacts,
    payload: dict[str, Any],
    bundle: AuditBundle,
    opinions: dict[str, dict[str, Any]],
) -> tuple[ExecutionMetadata, dict[str, Any]]:
    meta = ExecutionMetadata.model_validate(_json(reader.ref(refs.execution)))
    _require(
        meta.stage == name
        and meta.input_fingerprint == bundle.subject_hash
        and meta.prompt_version == payload["prompt_version"],
        "execution_subject_mismatch",
    )
    _require(
        not meta.fallback_used
        and meta.exit_code == 0
        and meta.cwd_isolated
        and meta.user_config_ignored,
        "execution_failed_or_not_isolated",
    )
    _require(
        _time(bundle.release.data_cutoff)
        <= _time(meta.started_at)
        <= _time(meta.completed_at)
        <= _time(bundle.release.frozen_at),
        "execution_time_invalid",
    )
    _argv(
        meta,
        has_runtime_identity=refs.runtime_identity is not None,
        require_isolation=bundle.data_classification != "synthetic",
    )
    for expected, actual in (
        (meta.prompt_sha256, refs.prompt.sha256),
        (meta.response_sha256, refs.response.sha256),
        (meta.stdout_sha256, refs.trace.sha256),
        (meta.stderr_sha256, refs.stderr.sha256),
    ):
        _require(expected == actual, "execution_artifact_hash_mismatch")
    schema = _json(reader.ref(refs.output_schema))
    _require(
        schema.get("type") == "object"
        and isinstance(schema.get("properties"), dict)
        and schema["properties"]
        and object_sha256(schema) == meta.schema_sha256,
        "execution_schema_invalid",
    )
    template = reader.ref(refs.template).decode("utf-8")
    _require(template.strip() and INPUT_MARKER not in template, "prompt_template_invalid")
    expected_payload = dict(payload)
    if name == "arbitration":
        expected_payload["independent_opinions"] = [opinions["primary"], opinions["adversarial"]]
    prompt = reader.ref(refs.prompt).decode("utf-8")
    _require(prompt.startswith(template + INPUT_MARKER), "prompt_template_mismatch")
    prompt_input = prompt[len(template + INPUT_MARKER) :].encode("utf-8")
    _require(
        object_sha256(_json(prompt_input)) == object_sha256(expected_payload),
        "prompt_packet_or_context_mismatch",
    )
    response = reader.ref(refs.response)
    opinion = _json(response)
    _require(
        opinion.get("stage") == name
        and type(opinion.get("target_id")) is int
        and opinion["target_id"] == payload["target_id"]
        and opinion.get("input_fingerprint") == bundle.subject_hash
        and opinion.get("decision") in {decision.value for decision in Decision}
        and isinstance(opinion.get("conditions"), list)
        and all(isinstance(c, str) for c in opinion["conditions"]),
        "response_subject_invalid",
    )
    if refs.runtime_identity is not None:
        _runtime_identity(
            reader, refs.runtime_identity, meta, prompt, response, bundle.release.frozen_at
        )
    _trace(
        reader.ref(refs.trace),
        response,
        meta,
        runtime_identity_verified=refs.runtime_identity is not None,
    )
    reader.ref(refs.stderr)
    return meta, opinion


def _independence(
    reader: _Reader,
    bundle: AuditBundle,
    executions: dict[str, ExecutionMetadata],
) -> None:
    for field in ("session_id", "audit_id", "cwd"):
        values = [
            getattr(meta, field).replace("\\", "/").casefold() for meta in executions.values()
        ]
        _require(len(set(values)) == len(values), "cross_stage_context_reuse")
    roots = [PurePosixPath(meta.cwd.replace("\\", "/").casefold()) for meta in executions.values()]
    _require(
        not any(
            a.is_relative_to(b) or b.is_relative_to(a)
            for index, a in enumerate(roots)
            for b in roots[index + 1 :]
        ),
        "cross_stage_context_reuse",
    )
    runtime_turns = []
    for name in executions:
        native = getattr(bundle.stages, name).runtime_identity
        if native is not None:
            runtime_turns.append(_json(reader.ref(native.capture))["turn_id"])
    _require(len(runtime_turns) == len(set(runtime_turns)), "cross_stage_runtime_turn_reuse")
    for name in ("primary", "adversarial"):
        refs = getattr(bundle.stages, name)
        context_parts = [reader.ref(refs.template).decode("utf-8")]
        if refs.runtime_identity is not None:
            for line in reader.ref(refs.runtime_identity.trace).splitlines():
                if not line.strip():
                    continue
                event = _json(line)
                payload = event["payload"]
                if event["type"] == "response_item" and payload.get("role") in {
                    "system",
                    "developer",
                }:
                    context_parts.append(_runtime_message_text(payload))
                if event["type"] == "session_meta" and isinstance(
                    payload.get("base_instructions"), dict
                ):
                    text = payload["base_instructions"].get("text")
                    if isinstance(text, str):
                        context_parts.append(text)
                if event["type"] == "turn_context":
                    for key in ("developer_instructions", "user_instructions"):
                        if isinstance(payload.get(key), str):
                            context_parts.append(payload[key])
        template = "\n".join(context_parts)
        for other, meta in executions.items():
            if other == name:
                continue
            other_refs = getattr(bundle.stages, other)
            raw_response = reader.ref(other_refs.response).decode("utf-8").strip()
            summary = _json(reader.ref(other_refs.response)).get("reasoning_summary")
            if isinstance(summary, str) and len(summary) >= 32:
                _require(summary not in template, "cross_stage_prompt_contamination")
            _require(
                all(
                    token not in template
                    for token in (
                        meta.session_id,
                        meta.audit_id,
                        meta.response_sha256,
                        raw_response,
                    )
                ),
                "cross_stage_prompt_contamination",
            )
    arbitration = executions.get("arbitration")
    if arbitration:
        _require(
            all(
                _time(meta.completed_at) <= _time(arbitration.started_at)
                for name, meta in executions.items()
                if name != "arbitration"
            ),
            "arbitration_precedes_reviews",
        )


def _evaluation(
    reader: _Reader,
    bundle: AuditBundle,
    executions: dict[str, ExecutionMetadata],
    now: datetime,
    max_eval_age: timedelta,
) -> EvaluationResult:
    plan = EvaluationPlan.model_validate(_json(reader.ref(bundle.evaluation_plan)))
    result = EvaluationResult.model_validate(_json(reader.ref(bundle.evaluation)))
    _require(
        result.release_id == bundle.release.release_id
        and result.artifact_fingerprint == bundle.release.artifact_fingerprint
        and result.model_identity_sha256 == actual_model_identity_sha256(executions),
        "evaluation_release_binding_mismatch",
    )
    _require(
        _time(bundle.release.frozen_at)
        <= _time(result.started_at)
        <= _time(result.completed_at)
        <= now
        and now - _time(result.started_at) <= max_eval_age,
        "evaluation_not_fresh",
    )
    _require(
        result.suite_code == plan.suite_code and result.suite_version == plan.suite_version,
        "evaluation_suite_mismatch",
    )
    cases = {case.case_code: case.model_dump() for case in plan.cases}
    actual = {
        case.case_code: case.model_dump(include={"case_code", "category", "severity"})
        for case in result.results
    }
    _require(
        len(cases) == len(plan.cases)
        and len(actual) == len(result.results)
        and cases == actual
        and {c.category for c in plan.cases} >= REQUIRED_EVAL_CATEGORIES,
        "evaluation_case_coverage_incomplete",
    )
    _require(
        result.full_chain_coverage
        and result.model_judge_executed
        and not result.coverage_gaps
        and not result.critical_failures
        and result.failed == 0
        and result.skipped == 0
        and result.case_count == result.passed == len(plan.cases)
        and all(case.passed and case.error is None for case in result.results),
        "evaluation_failed_or_incomplete",
    )
    return result


def validate_audit_bundle(
    audit_dir: Path,
    *,
    expected_release_id: str,
    expected_artifact_fingerprint: str,
    expected_subject_hash: str,
    expected_manifest_sha256: str,
    manifest_path: str = "audit_bundle.json",
    policy_path: Path = DEFAULT_POLICY,
    now: datetime | None = None,
    max_eval_age: timedelta = timedelta(days=1),
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """Fail closed; policy_satisfied is the sole INTERNAL RC alternative result.

    ``valid`` means structural/evidence validation only. Synthetic verification
    can set valid=True, but NEVER policy_satisfied=True. No other Gate or data
    approval follows from either field. Errors contain no untrusted content.
    """
    result: dict[str, Any] = {
        "valid": False,
        "policy_satisfied": False,
        "status": "BLOCKED",
        "errors": [],
        "scope": "internal_release_candidate_only",
        "snapshot_pinned": False,
        "immutable_snapshot_claimed": False,
        "alias_may_change": True,
        "model_reexecution_nondeterministic": True,
        "customer_output_allowed": False,
        "production_apply_allowed": False,
        "database_writeback": False,
        "aggregate_gate_updated": False,
    }
    try:
        _require(
            isinstance(expected_release_id, str)
            and expected_release_id.strip()
            and _digest(expected_artifact_fingerprint)
            and _digest(expected_subject_hash)
            and _digest(expected_manifest_sha256),
            "trusted_release_expectations_required",
        )
        current = now or datetime.now(UTC)
        _require(
            current.tzinfo is not None and current.utcoffset() is not None, "timezone_required"
        )
        current = current.astimezone(UTC)
        _require(timedelta(0) < max_eval_age <= timedelta(days=1), "eval_age_limit_invalid")
        reader = _Reader(audit_dir)
        manifest_bytes = reader.read(manifest_path)
        _require(
            sha256(manifest_bytes).hexdigest() == expected_manifest_sha256,
            "sealed_manifest_hash_mismatch",
        )
        bundle = AuditBundle.model_validate(_json(manifest_bytes))
        policy_bytes = policy_path.read_bytes()
        _policy(policy_bytes)
        _require(reader.ref(bundle.policy) == policy_bytes, "policy_copy_mismatch")
        _scope(bundle, allow_synthetic)
        _require(
            bundle.release.release_id == expected_release_id
            and bundle.subject_hash == expected_subject_hash
            and bundle.release.artifact_fingerprint
            == expected_artifact_fingerprint
            == compute_artifact_fingerprint(bundle),
            "release_fingerprint_mismatch",
        )
        _require(
            _time(bundle.release.data_cutoff) <= _time(bundle.release.frozen_at) <= current,
            "release_time_invalid",
        )

        # Verify every reference, including opaque release artifacts, before consumption.
        def visit(value: object) -> None:
            if isinstance(value, FileRef):
                reader.ref(value)
            elif isinstance(value, BaseModel):
                for field in type(value).model_fields:
                    visit(getattr(value, field))
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(bundle)
        _require(
            all(reader.ref(ref).strip() for ref in (bundle.code, bundle.rules, bundle.data)),
            "release_artifact_empty",
        )
        payload = _packet(reader, bundle)
        opinions: dict[str, dict[str, Any]] = {}
        executions: dict[str, ExecutionMetadata] = {}
        for name in ("primary", "adversarial", "arbitration"):
            refs = getattr(bundle.stages, name)
            if refs is not None:
                executions[name], opinions[name] = _stage(
                    reader, name, refs, payload, bundle, opinions
                )
        disagreement = any(
            opinions["primary"][key] != opinions["adversarial"][key]
            for key in ("decision", "conditions")
        )
        _require(not disagreement or "arbitration" in executions, "arbitration_required")
        _independence(reader, bundle, executions)
        evaluation = _evaluation(reader, bundle, executions, current, max_eval_age)
        reader.unchanged()
        synthetic = bundle.data_classification == "synthetic"
        result.update(
            valid=True,
            policy_satisfied=not synthetic,
            status="SYNTHETIC_VERIFIED" if synthetic else "VERIFIED_INTERNAL_RC",
            release_id=bundle.release.release_id,
            artifact_fingerprint=bundle.release.artifact_fingerprint,
            manifest_sha256=expected_manifest_sha256,
            subject_hash=bundle.subject_hash,
            model_id=MODEL_ID,
            model_version="alias_unresolved",
            evaluation_run_id=evaluation.run_id,
            verified_files=len(reader.files),
        )
    except BundleError as exc:
        result["errors"] = [str(exc)]
    except ValidationError:
        result["errors"] = ["schema_validation_failed"]
    except (OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError):
        result["errors"] = ["unreadable_or_malformed_bundle"]
    return result


def audit_bundle_schema() -> dict[str, Any]:
    """Machine-readable builder contracts; this function grants no authorization."""
    return {
        "manifest": AuditBundle.model_json_schema(),
        "execution": ExecutionMetadata.model_json_schema(),
        "evaluation_plan": EvaluationPlan.model_json_schema(),
        "evaluation": EvaluationResult.model_json_schema(),
        "runtime_capture": RuntimeCaptureProvenance.model_json_schema(),
        "required_eval_categories": sorted(REQUIRED_EVAL_CATEGORIES),
        "trace_contract": {
            "format": "UTF-8 JSONL, complete unedited runtime stdout",
            "first": {"type": "thread.started", "thread_id": "actual runtime session ID"},
            "second": {"type": "turn.started", "model": MODEL_ID, "model_provider": "openai"},
            "startup_notice": (
                "Only the exact disabled code-mode-host item_0 error may precede turn.started; "
                "validate_review_cli_events omits it from the validated view, never raw stdout"
            ),
            "identity_alternative": "model/provider may be absent ONLY with verified runtime_identity attachments",
            "middle": "item.started/updated/completed; reasoning or agent_message only",
            "response": "exactly one completed agent_message matching response_id and full raw response",
            "last": {"type": "turn.completed"},
            "identity": "Runtime-reported only. Never synthesize missing model fields from argv.",
        },
        "runtime_session_contract": {
            "attachment": "stages.<stage>.runtime_identity = {trace: FileRef, capture: FileRef}",
            "format": "Original native UTF-8 session JSONL, complete single isolated turn; no reconstructed events",
            "identity": "session_meta.payload.id/model_provider and turn_context.payload.turn_id/model/effort/cwd",
            "provenance": "capture.audit_id=stage execution audit_id, session_id=stdout thread.started.thread_id, turn_id=native task/turn ID; hash exact bytes",
            "binding": "task_started/turn_context/task_complete agree on turn_id, no parent/root-turn reuse, timestamps inside execution; capture after completion and before release freeze",
            "input": "Legacy synthetic: one exact prompt. Isolated: exact pinned developer/environment prefix, one exact prompt, and its bound UserMessage event",
            "isolation": "Non-synthetic stages require runtime_isolation and complete verified native capture; clean profile pins all session/context/world and generated input fields",
            "response": "task_complete.last_agent_message equals complete response, plus any native assistant final messages",
            "blocked": "Missing identity/completion/input, multiple turns, tools, unverified world_state, inherited rules/skills/instructions, compacted or unknown events",
            "privacy": "Keep local with access controls; do not transmit runtime account metadata to model reviewers or inspect auth files",
        },
        "builder_steps": __doc__,
    }
