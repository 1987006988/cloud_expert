"""Synthetic-only audit fixtures. No real model call, cloud fact, DB or Gate write."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from cloud_expert.model_review import reproducibility as audit
from cloud_expert.model_review.schemas import Decision

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 30, 3, tzinfo=UTC)


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


class SyntheticBundle:
    def __init__(self, root):
        self.root = root
        self.policy = audit.DEFAULT_POLICY
        snapshot = self.write("evidence/source.txt", b"SYNTHETIC source, not an official fact.")
        excerpt = "SYNTHETIC excerpt, never real data."
        self.packet = {
            "target_id": 1,
            "target_type": "candidate_decision_result",
            "data_classification": "synthetic",
            "precheck": "passed",
            "authorization_scope": "public_evidence_internal_report_only",
            "prompt_version": "decision-panel.synthetic.v1",
            "subject": {"id": 1},
            "evidence": [
                {
                    "evidence_id": 1,
                    "source_document_id": 2,
                    "snapshot_id": 3,
                    "source_sha256": snapshot["sha256"],
                    "excerpt": excerpt,
                    "excerpt_sha256": sha256(excerpt.encode()).hexdigest(),
                    "captured_at": "2026-09-30T00:00:00+00:00",
                }
            ],
        }
        self.subject = {
            "records": [{"table": "synthetic", "id": 1, "sha256": "a" * 64}],
            "mapping_approval_sha256": "b" * 64,
            "implementation": {"synthetic.py": "c" * 64},
            "public_payload_sha256": audit.object_sha256(self.packet),
        }
        subject_hash = audit.object_sha256(self.subject)
        self.packet["input_fingerprint"] = subject_hash
        self.manifest = {
            "schema_version": audit.SCHEMA_VERSION,
            "data_classification": "synthetic",
            "policy": self.write("policy.yaml", self.policy.read_bytes()),
            "scope": {
                "mode": "release_candidate",
                "audience": "internal_only",
                "production_apply_allowed": False,
                "customer_output_allowed": False,
            },
            "disclosures": {
                "alias_may_change": True,
                "model_reexecution_nondeterministic": True,
                "immutable_snapshot_claimed": False,
                "preserved_record_replay_only": True,
            },
            "release": {
                "release_id": "synthetic-rc-001",
                "frozen_at": "2026-09-30T02:20:00+00:00",
                "data_cutoff": "2026-09-30T01:00:00+00:00",
                "model_id": audit.MODEL_ID,
                "model_version": "alias_unresolved",
                "artifact_fingerprint": "0" * 64,
            },
            "code": self.write("release/code.txt", b"SYNTHETIC code snapshot"),
            "rules": self.write("release/rules.json", {"synthetic_rule": "v1"}),
            "data": self.write("release/data.json", {"synthetic_dataset": "v1"}),
            "input": self.write("input.json", self.packet),
            "subject": self.write("fingerprint.json", self.subject),
            "subject_hash": subject_hash,
            "evidence": [{"evidence_id": 1, "source_document_id": 2, "snapshot": snapshot}],
            "stages": {},
        }
        self.opinions = {}
        self.executions = {}
        self.events = {}
        self.runtime_traces = {}
        self.runtime_captures = {}
        for index, stage in enumerate(("primary", "adversarial", "arbitration")):
            self.build_stage(stage, index)
        self.plan = {
            "suite_code": "SYNTHETIC-ONLY",
            "suite_version": "synthetic.v1",
            "cases": [
                {"case_code": f"synthetic.{category}", "category": category, "severity": "critical"}
                for category in sorted(audit.REQUIRED_EVAL_CATEGORIES)
            ],
        }
        self.manifest["evaluation_plan"] = self.write("eval/plan.json", self.plan)
        self.evaluation = {
            "schema_version": "internal_rc_evaluation.v1",
            "run_id": "synthetic-eval-001",
            "release_id": self.manifest["release"]["release_id"],
            "artifact_fingerprint": "0" * 64,
            "model_identity_sha256": "0" * 64,
            "suite_code": self.plan["suite_code"],
            "suite_version": self.plan["suite_version"],
            "started_at": "2026-09-30T02:30:00+00:00",
            "completed_at": "2026-09-30T02:40:00+00:00",
            "status": "succeeded",
            "full_chain_coverage": True,
            "model_judge_executed": True,
            "coverage_gaps": [],
            "case_count": len(self.plan["cases"]),
            "passed": len(self.plan["cases"]),
            "failed": 0,
            "skipped": 0,
            "critical_failures": [],
            "results": [
                {
                    **case,
                    "passed": True,
                    "expected": "synthetic",
                    "actual": "synthetic",
                    "error": None,
                }
                for case in self.plan["cases"]
            ],
        }
        self.seal()

    def write(self, name, value):
        raw = value if isinstance(value, bytes) else encode(value)
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": name, "sha256": sha256(raw).hexdigest()}

    def build_stage(self, stage, index):
        opinion = {
            "stage": stage,
            "target_id": 1,
            "input_fingerprint": self.manifest["subject_hash"],
            "decision": "model_approved" if stage == "primary" else "model_blocked",
            "conditions": [],
            "reasoning_summary": f"SYNTHETIC ONLY {stage} opinion.",
        }
        self.opinions[stage] = opinion
        payload = copy.deepcopy(self.packet)
        if stage == "arbitration":
            payload["independent_opinions"] = [
                self.opinions["primary"],
                self.opinions["adversarial"],
            ]
        template = f"SYNTHETIC ONLY. Independently execute {stage}."
        schema = {"type": "object", "properties": {"stage": {"type": "string"}}}
        refs = {
            "template": self.write(f"{stage}/template.txt", template.encode()),
            "prompt": self.write(
                f"{stage}/prompt.txt",
                template.encode() + audit.INPUT_MARKER.encode() + encode(payload),
            ),
            "schema": self.write(f"{stage}/schema.json", schema),
            "response": self.write(f"{stage}/response.raw.json", opinion),
            "stderr": self.write(f"{stage}/stderr.txt", b""),
        }
        cwd = f"C:/synthetic-isolated-{stage}"
        command = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--strict-config",
            "-m",
            audit.MODEL_ID,
            "-c",
            'model_reasoning_effort="max"',
            "-c",
            'model_provider="openai"',
            "-c",
            "project_doc_max_bytes=0",
            "-c",
            'web_search="disabled"',
            "--ephemeral",
            "-s",
            "read-only",
            "--skip-git-repo-check",
            "--json",
            "--output-schema",
            f"{cwd}/schema.json",
            "-o",
            f"{cwd}/response.json",
        ]
        for feature in sorted(audit.DISABLED_FEATURES):
            command.extend(["--disable", feature])
        command.append("-")
        meta = {
            "stage": stage,
            "model_id": audit.MODEL_ID,
            "actual_model_id": audit.MODEL_ID,
            "model_provider": "openai",
            "model_version": "alias_unresolved",
            "fallback_used": False,
            "prompt_version": self.packet["prompt_version"],
            "prompt_sha256": refs["prompt"]["sha256"],
            "schema_sha256": audit.object_sha256(schema),
            "input_fingerprint": self.manifest["subject_hash"],
            "audit_id": str(uuid4()),
            "session_id": str(uuid4()),
            "response_id": "item_0",
            "started_at": f"2026-09-30T02:0{index * 2}:00+00:00",
            "completed_at": f"2026-09-30T02:0{index * 2 + 1}:00+00:00",
            "status": "completed",
            "argv": command,
            "argv_sha256": audit.object_sha256(command),
            "reasoning_effort": "max",
            "cwd": cwd,
            "cwd_isolated": True,
            "user_config_ignored": True,
            "schema_path": f"{cwd}/schema.json",
            "response_path": f"{cwd}/response.json",
            "exit_code": 0,
            "stdout_sha256": "0" * 64,
            "stderr_sha256": refs["stderr"]["sha256"],
            "response_sha256": refs["response"]["sha256"],
        }
        self.events[stage] = [
            {"type": "thread.started", "thread_id": meta["session_id"]},
            {"type": "turn.started", "model": audit.MODEL_ID, "model_provider": "openai"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "id": "item_0", "text": encode(opinion).decode()},
            },
            {"type": "turn.completed", "usage": {"output_tokens": 100}},
        ]
        self.executions[stage] = meta
        self.manifest["stages"][stage] = refs
        self.save_trace(stage)

    def save_meta(self, stage):
        refs = self.manifest["stages"][stage]
        refs["execution"] = self.write(f"{stage}/execution.json", self.executions[stage])

    def save_trace(self, stage):
        refs = self.manifest["stages"][stage]
        refs["trace"] = self.write(
            f"{stage}/stdout.jsonl", b"\n".join(map(encode, self.events[stage]))
        )
        self.executions[stage]["stdout_sha256"] = refs["trace"]["sha256"]
        self.save_meta(stage)

    def attach_runtime_identity(self, stage, *, persistent=False):
        meta = self.executions[stage]
        self.events[stage][1] = {"type": "turn.started"}
        if persistent:
            meta["argv"].remove("--ephemeral")
            meta["argv_sha256"] = audit.object_sha256(meta["argv"])
        self.save_trace(stage)
        turn_id = str(uuid4())
        refs = self.manifest["stages"][stage]
        prompt = (self.root / refs["prompt"]["path"]).read_bytes().decode()
        response = (self.root / refs["response"]["path"]).read_bytes().decode()

        def event(kind, payload, *, complete=False):
            return {
                "type": kind,
                "timestamp": meta["completed_at"] if complete else meta["started_at"],
                "payload": payload,
            }

        self.runtime_traces[stage] = [
            event(
                "session_meta",
                {
                    "id": meta["session_id"],
                    "cwd": meta["cwd"],
                    "model_provider": "openai",
                    "cli_version": "0.158.0-synthetic",
                    "parent_thread_id": None,
                },
            ),
            event(
                "event_msg", {"type": "task_started", "turn_id": turn_id, "root_turn_id": turn_id}
            ),
            event(
                "turn_context",
                {
                    "turn_id": turn_id,
                    "root_turn_id": turn_id,
                    "model": audit.MODEL_ID,
                    "effort": "max",
                    "cwd": meta["cwd"],
                },
            ),
            event(
                "response_item",
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
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
            event(
                "event_msg",
                {"type": "task_complete", "turn_id": turn_id, "last_agent_message": response},
                complete=True,
            ),
        ]
        self.runtime_captures[stage] = {
            "schema_version": "codex_runtime_session_capture.v1",
            "source_format": "codex_session_jsonl",
            "audit_id": meta["audit_id"],
            "session_id": meta["session_id"],
            "turn_id": turn_id,
            "source_basename": f"rollout-2026-09-30T02-00-00-{meta['session_id']}.jsonl",
            "cli_version": "0.158.0-synthetic",
            "captured_at": meta["completed_at"],
            "trace_sha256": "0" * 64,
        }
        self.save_runtime(stage)

    def save_runtime(self, stage):
        trace = self.write(
            f"{stage}/runtime-session.jsonl", b"\n".join(map(encode, self.runtime_traces[stage]))
        )
        self.runtime_captures[stage]["trace_sha256"] = trace["sha256"]
        capture = self.write(f"{stage}/runtime-capture.json", self.runtime_captures[stage])
        self.manifest["stages"][stage]["runtime_identity"] = {"trace": trace, "capture": capture}

    def save_prompt(self, stage, raw):
        refs = self.manifest["stages"][stage]
        refs["prompt"] = self.write(f"{stage}/prompt.txt", raw)
        self.executions[stage]["prompt_sha256"] = refs["prompt"]["sha256"]
        self.save_meta(stage)

    def rebind_packet(self):
        self.subject["public_payload_sha256"] = audit.object_sha256(
            {k: v for k, v in self.packet.items() if k != "input_fingerprint"}
        )
        self.manifest["subject_hash"] = audit.object_sha256(self.subject)
        self.packet["input_fingerprint"] = self.manifest["subject_hash"]
        self.manifest["subject"] = self.write("fingerprint.json", self.subject)
        self.manifest["input"] = self.write("input.json", self.packet)
        for opinion in self.opinions.values():
            opinion["input_fingerprint"] = self.manifest["subject_hash"]
        for stage, refs in self.manifest["stages"].items():
            if refs is None:
                continue
            refs["response"] = self.write(refs["response"]["path"], self.opinions[stage])
            self.executions[stage]["response_sha256"] = refs["response"]["sha256"]
            self.executions[stage]["input_fingerprint"] = self.manifest["subject_hash"]
            self.events[stage][2]["item"]["text"] = encode(self.opinions[stage]).decode()
            self.save_trace(stage)
            data = copy.deepcopy(self.packet)
            if stage == "arbitration":
                data["independent_opinions"] = [
                    self.opinions["primary"],
                    self.opinions["adversarial"],
                ]
            self.save_prompt(
                stage,
                (self.root / refs["template"]["path"]).read_bytes()
                + audit.INPUT_MARKER.encode()
                + encode(data),
            )
        self.seal()

    def seal(self, *, rebind_eval=True):
        self.manifest["release"]["artifact_fingerprint"] = audit.compute_artifact_fingerprint(
            self.manifest
        )
        if rebind_eval:
            self.evaluation["release_id"] = self.manifest["release"]["release_id"]
            self.evaluation["artifact_fingerprint"] = self.manifest["release"][
                "artifact_fingerprint"
            ]
            # model_construct deliberately permits malformed metadata in negative fixtures.
            self.evaluation["model_identity_sha256"] = audit.actual_model_identity_sha256(
                {
                    name: audit.ExecutionMetadata.model_construct(**meta)
                    for name, meta in self.executions.items()
                    if self.manifest["stages"].get(name)
                }
            )
        self.manifest["evaluation"] = self.write("eval/result.json", self.evaluation)
        self.manifest_sha256 = self.write("audit_bundle.json", self.manifest)["sha256"]

    def check(self, **kwargs):
        options = {
            "expected_release_id": self.manifest["release"]["release_id"],
            "expected_artifact_fingerprint": self.manifest["release"]["artifact_fingerprint"],
            "expected_subject_hash": self.manifest["subject_hash"],
            "expected_manifest_sha256": self.manifest_sha256,
            "now": NOW,
            "allow_synthetic": True,
        }
        options.update(kwargs)
        return audit.validate_audit_bundle(self.root, **options)


@pytest.fixture
def bundle(tmp_path):
    return SyntheticBundle(tmp_path)


def blocked(result, code=None):
    assert result["status"] == "BLOCKED"
    assert not result["valid"] and not result["policy_satisfied"]
    assert not result["customer_output_allowed"] and not result["production_apply_allowed"]
    assert not result["database_writeback"] and not result["aggregate_gate_updated"]
    if code:
        assert result["errors"] == [code]


def test_complete_synthetic_bundle_is_never_a_real_release_pass(bundle):
    before = {p: p.read_bytes() for p in bundle.root.rglob("*") if p.is_file()}
    result = bundle.check()
    assert result["valid"] and result["status"] == "SYNTHETIC_VERIFIED"
    assert not result["policy_satisfied"] and not result["snapshot_pinned"]
    assert result["model_version"] == "alias_unresolved"
    assert result["alias_may_change"] and result["model_reexecution_nondeterministic"]
    assert before == {p: p.read_bytes() for p in bundle.root.rglob("*") if p.is_file()}
    blocked(bundle.check(allow_synthetic=False), "synthetic_cannot_authorize_release")


def test_authorization_yaml_alone_never_passes(bundle):
    (bundle.root / "audit_bundle.json").unlink()
    blocked(bundle.check())
    bundle.write("audit_bundle.json", {"policy": bundle.manifest["policy"]})
    blocked(bundle.check())


@pytest.mark.parametrize(
    "name",
    [
        "release/code.txt",
        "release/rules.json",
        "release/data.json",
        "input.json",
        "fingerprint.json",
        "evidence/source.txt",
        "policy.yaml",
        "primary/prompt.txt",
        "adversarial/response.raw.json",
        "arbitration/stdout.jsonl",
        "primary/execution.json",
        "eval/result.json",
    ],
)
def test_file_tampering_is_detected(bundle, name):
    with (bundle.root / name).open("ab") as handle:
        handle.write(b"tampered")
    blocked(bundle.check())


@pytest.mark.parametrize(
    "name",
    [
        "primary/response.raw.json",
        "adversarial/stdout.jsonl",
        "arbitration/response.raw.json",
        "arbitration/stdout.jsonl",
        "primary/execution.json",
        "eval/plan.json",
        "eval/result.json",
    ],
)
def test_missing_full_responses_and_traces_fail_closed(bundle, name):
    (bundle.root / name).unlink()
    blocked(bundle.check())


@pytest.mark.parametrize(
    "path",
    [
        "../outside.json",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "C:relative.txt",
        "//server/share/file",
        "..\\outside.json",
        "primary/../input.json",
        "primary//prompt.txt",
        "./input.json",
        "input.json:stream",
        "primary /prompt.txt",
        "primary./prompt.txt",
    ],
)
def test_manifest_paths_are_contained_even_with_fresh_hash_binding(bundle, path):
    bundle.manifest["code"]["path"] = path
    bundle.seal()
    blocked(bundle.check(), "unsafe_artifact_path")


def test_manifest_itself_cannot_escape(bundle):
    blocked(bundle.check(manifest_path="../audit_bundle.json"), "unsafe_artifact_path")


def test_symlink_escape_rejected(bundle):
    outside = bundle.root.parent / f"outside-{uuid4().hex}.txt"
    outside.write_bytes(b"SYNTHETIC")
    link = bundle.root / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        # Windows installations without symbolic-link privileges still exercise
        # the path policy via a simulated OS link classification.
        pytest.skip("OS does not permit creating symbolic links")
    bundle.manifest["code"] = {
        "path": link.name,
        "sha256": sha256(outside.read_bytes()).hexdigest(),
    }
    bundle.seal()
    blocked(bundle.check(), "linked_artifact_path")


def test_hardlinked_artifact_rejected(bundle):
    link = bundle.root / "linked-code.txt"
    os.link(bundle.root / "release/code.txt", link)
    bundle.manifest["code"]["path"] = link.name
    bundle.seal()
    blocked(bundle.check(), "hardlinked_artifact")


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "production"),
        ("audience", "customer"),
        ("production_apply_allowed", True),
        ("customer_output_allowed", True),
    ],
)
def test_production_or_customer_scope_rejected(bundle, field, value):
    bundle.manifest["scope"][field] = value
    bundle.seal()
    blocked(bundle.check())


@pytest.mark.parametrize(
    "field,value",
    [
        ("alias_may_change", False),
        ("model_reexecution_nondeterministic", False),
        ("immutable_snapshot_claimed", True),
        ("preserved_record_replay_only", False),
    ],
)
def test_no_immutable_version_claim_or_suppressed_drift(bundle, field, value):
    bundle.manifest["disclosures"][field] = value
    bundle.seal()
    blocked(bundle.check(), "alias_drift_not_disclosed")


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_model_id", "weaker-model"),
        ("fallback_used", True),
        ("model_version", "invented-pinned-version"),
        ("model_provider", "other"),
        ("exit_code", 1),
        ("status", "failed"),
        ("cwd_isolated", False),
        ("user_config_ignored", False),
        ("reasoning_effort", "low"),
        ("prompt_version", "stale-prompt"),
        ("stage", "primary"),
        ("input_fingerprint", "f" * 64),
    ],
)
def test_actual_stage_metadata_and_no_fallback(bundle, field, value):
    bundle.executions["adversarial"][field] = value
    bundle.save_meta("adversarial")
    bundle.seal()
    blocked(bundle.check())


def test_requested_model_alone_does_not_attest_actual_model(bundle):
    del bundle.events["primary"][1]["model"]
    bundle.save_trace("primary")
    bundle.seal()
    blocked(bundle.check(), "actual_model_identity_unverified")


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_model",
        "wrong_thread",
        "tool",
        "failed_turn",
        "extra_turn",
        "truncated_response",
        "no_response",
        "resumed",
    ],
)
def test_full_native_trace_semantics(bundle, mutation):
    events = bundle.events["adversarial"]
    if mutation == "wrong_model":
        events[1]["model"] = "weaker-model"
    elif mutation == "wrong_thread":
        events[0]["thread_id"] = str(uuid4())
    elif mutation == "tool":
        events.insert(2, {"type": "item.completed", "item": {"type": "command_execution"}})
    elif mutation == "failed_turn":
        events[-1]["type"] = "turn.failed"
    elif mutation == "extra_turn":
        events.insert(2, {"type": "turn.started", "model": audit.MODEL_ID})
    elif mutation == "truncated_response":
        events[2]["item"]["text"] = "{}"
    elif mutation == "no_response":
        events[2]["item"]["type"] = "reasoning"
    elif mutation == "resumed":
        events[0]["resumed_from"] = "previous-session"
    bundle.save_trace("adversarial")
    bundle.seal()
    blocked(bundle.check())


@pytest.mark.parametrize("field", ["session_id", "audit_id", "cwd"])
def test_cross_stage_context_reuse_detected(bundle, field):
    primary = bundle.executions["primary"]
    adversarial = bundle.executions["adversarial"]
    adversarial[field] = primary[field]
    if field == "session_id":
        bundle.events["adversarial"][0]["thread_id"] = primary[field]
        bundle.save_trace("adversarial")
    elif field == "cwd":
        for key in ("schema_path", "response_path"):
            old = adversarial[key]
            adversarial[key] = primary[key]
            adversarial["argv"][adversarial["argv"].index(old)] = primary[key]
        adversarial["argv_sha256"] = audit.object_sha256(adversarial["argv"])
    bundle.save_meta("adversarial")
    bundle.seal()
    blocked(bundle.check(), "cross_stage_context_reuse")


def test_prior_opinion_cannot_be_hidden_in_adversarial_input(bundle):
    raw = (bundle.root / "adversarial/prompt.txt").read_bytes()
    prefix, payload = raw.split(audit.INPUT_MARKER.encode())
    data = json.loads(payload)
    data["independent_opinions"] = [bundle.opinions["primary"]]
    bundle.save_prompt("adversarial", prefix + audit.INPUT_MARKER.encode() + encode(data))
    bundle.seal()
    blocked(bundle.check(), "prompt_packet_or_context_mismatch")


def test_prior_opinion_cannot_be_hidden_in_prompt_template(bundle):
    refs = bundle.manifest["stages"]["adversarial"]
    template = b"SYNTHETIC prior review: " + encode(bundle.opinions["primary"])
    refs["template"] = bundle.write("adversarial/template.txt", template)
    bundle.save_prompt(
        "adversarial", template + audit.INPUT_MARKER.encode() + encode(bundle.packet)
    )
    bundle.seal()
    blocked(bundle.check(), "cross_stage_prompt_contamination")


def test_arbitration_required_for_disagreement(bundle):
    bundle.manifest["stages"]["arbitration"] = None
    bundle.seal()
    blocked(bundle.check(), "arbitration_required")


def test_arbitration_optional_only_when_independent_opinions_agree(bundle):
    bundle.opinions["adversarial"]["decision"] = "model_approved"
    opinion = bundle.opinions["adversarial"]
    refs = bundle.manifest["stages"]["adversarial"]
    refs["response"] = bundle.write(refs["response"]["path"], opinion)
    bundle.executions["adversarial"]["response_sha256"] = refs["response"]["sha256"]
    bundle.events["adversarial"][2]["item"]["text"] = encode(opinion).decode()
    bundle.save_trace("adversarial")
    bundle.manifest["stages"]["arbitration"] = None
    bundle.seal()
    assert bundle.check()["status"] == "SYNTHETIC_VERIFIED"


def test_arbitration_cannot_receive_modified_opinions(bundle):
    path = bundle.root / "arbitration/prompt.txt"
    raw = path.read_bytes().replace(b"model_blocked", b"model_approved")
    bundle.save_prompt("arbitration", raw)
    bundle.seal()
    blocked(bundle.check(), "prompt_packet_or_context_mismatch")


@pytest.mark.parametrize(
    "what", ["packet", "subject", "excerpt", "source_id", "evidence_after_cutoff"]
)
def test_frozen_packet_and_evidence_hash_relationships(bundle, what):
    if what == "packet":
        bundle.packet["subject"]["id"] = 2
    elif what == "subject":
        bundle.subject["records"][0]["sha256"] = "d" * 64
        bundle.manifest["subject"] = bundle.write("fingerprint.json", bundle.subject)
    elif what == "excerpt":
        bundle.packet["evidence"][0]["excerpt"] = "SYNTHETIC tamper"
    elif what == "source_id":
        bundle.manifest["evidence"][0]["source_document_id"] = 999
    elif what == "evidence_after_cutoff":
        bundle.packet["evidence"][0]["captured_at"] = "2026-10-01T00:00:00+00:00"
    bundle.manifest["input"] = bundle.write("input.json", bundle.packet)
    bundle.seal()
    blocked(bundle.check())


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_id", "old-release"),
        ("artifact_fingerprint", "f" * 64),
        ("model_identity_sha256", "e" * 64),
    ],
)
def test_eval_bound_to_exact_release_and_actual_model_runs(bundle, field, value):
    bundle.evaluation[field] = value
    bundle.seal(rebind_eval=False)
    blocked(bundle.check(), "evaluation_release_binding_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("started_at", "2026-09-30T02:00:00+00:00"),
        ("completed_at", "2026-10-01T00:00:00+00:00"),
        ("completed_at", "2026-09-30T02:25:00+00:00"),
        ("started_at", "2026-09-30T02:30:00"),
    ],
)
def test_eval_must_be_fresh_after_freeze_not_future_or_naive(bundle, field, value):
    bundle.evaluation[field] = value
    bundle.seal()
    blocked(bundle.check())


def test_old_complete_eval_is_rejected(bundle):
    blocked(bundle.check(now=NOW + timedelta(days=1)), "evaluation_not_fresh")
    blocked(bundle.check(max_eval_age=timedelta(days=2)), "eval_age_limit_invalid")


def test_code_change_cannot_reuse_old_eval(bundle):
    bundle.manifest["code"] = bundle.write("release/code.txt", b"SYNTHETIC code revision 2")
    bundle.seal(rebind_eval=False)
    blocked(bundle.check(), "evaluation_release_binding_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("critical_failures", ["synthetic.critical"]),
        ("failed", 1),
        ("skipped", 1),
        ("passed", 1),
        ("case_count", 1),
        ("full_chain_coverage", False),
        ("model_judge_executed", False),
        ("coverage_gaps", ["ui"]),
        ("suite_version", "old"),
        ("status", "failed"),
    ],
)
def test_eval_success_is_not_just_an_authorization_or_boolean(bundle, field, value):
    bundle.evaluation[field] = value
    bundle.seal()
    blocked(bundle.check())


@pytest.mark.parametrize("mutation", ["failed", "error", "missing", "duplicate", "wrong_severity"])
def test_individual_eval_cases_checked_against_frozen_inventory(bundle, mutation):
    cases = bundle.evaluation["results"]
    if mutation == "failed":
        cases[0]["passed"] = False
    elif mutation == "error":
        cases[0]["error"] = "synthetic failure"
    elif mutation == "missing":
        cases.pop()
    elif mutation == "duplicate":
        cases[-1] = copy.deepcopy(cases[0])
    else:
        cases[0]["severity"] = "low"
    bundle.seal()
    blocked(bundle.check())


def test_category_removal_cannot_be_hidden_by_changing_plan_and_results(bundle):
    bundle.plan["cases"].pop()
    bundle.evaluation["results"].pop()
    bundle.evaluation["passed"] -= 1
    bundle.evaluation["case_count"] -= 1
    bundle.manifest["evaluation_plan"] = bundle.write("eval/plan.json", bundle.plan)
    bundle.seal()
    blocked(bundle.check(), "evaluation_case_coverage_incomplete")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_release_id": "another-rc"},
        {"expected_artifact_fingerprint": "a" * 64},
        {"expected_subject_hash": "d" * 64},
        {"expected_release_id": ""},
        {"expected_subject_hash": None},
    ],
)
def test_external_release_expectations_required(bundle, kwargs):
    blocked(bundle.check(**kwargs))


def test_tight_schema_rejects_unknown_fields_and_bool_as_int(bundle):
    bundle.manifest["authorized"] = True
    bundle.seal()
    blocked(bundle.check(), "schema_validation_failed")
    del bundle.manifest["authorized"]
    bundle.evaluation["failed"] = False
    bundle.seal()
    blocked(bundle.check(), "schema_validation_failed")


@pytest.mark.parametrize("raw", [b"{", b"[]", b'{"x": 1, "x": 2}', b'{"x": NaN}'])
def test_malformed_and_ambiguous_json_fail_closed(bundle, raw):
    bundle.write("audit_bundle.json", raw)
    blocked(bundle.check(expected_manifest_sha256=sha256(raw).hexdigest()))


def test_missing_policy_does_not_raise_or_leak_paths(bundle):
    result = bundle.check(policy_path=bundle.root / "SECRET-DO-NOT-PRINT")
    blocked(result)
    assert "SECRET" not in json.dumps(result)


def test_policy_relaxation_is_rejected_even_with_matching_copy(bundle):
    raw = bundle.policy.read_bytes().replace(
        b"owner_authorization_alone_passes: false", b"owner_authorization_alone_passes: true"
    )
    bundle.manifest["policy"] = bundle.write("policy.yaml", raw)
    bundle.seal()
    blocked(bundle.check(policy_path=bundle.root / "policy.yaml"), "policy_gate_semantics_invalid")


def test_argv_context_or_tool_overrides_rejected(bundle):
    meta = bundle.executions["primary"]
    meta["argv"].insert(-1, "--resume")
    meta["argv_sha256"] = audit.object_sha256(meta["argv"])
    bundle.save_meta("primary")
    bundle.seal()
    blocked(bundle.check(), "execution_features_not_isolated")


def test_exported_schemas_and_hash_builder_are_not_a_pass(bundle):
    schema = audit.audit_bundle_schema()
    assert schema["manifest"]["additionalProperties"] is False
    assert "builder_steps" in schema and "trace_contract" in schema
    model = audit.AuditBundle.model_validate(bundle.manifest)
    assert (
        audit.compute_artifact_fingerprint(model)
        == bundle.manifest["release"]["artifact_fingerprint"]
    )
    (bundle.root / "primary/stdout.jsonl").unlink()
    assert (
        audit.compute_artifact_fingerprint(model)
        == bundle.manifest["release"]["artifact_fingerprint"]
    )
    blocked(bundle.check())


def test_cli_schema_command():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_model_audit_bundle.py"), "--schema"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "manifest" in json.loads(completed.stdout)


def test_cli_synthetic_exit_code_cannot_be_used_as_release_success(bundle, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "verify_bundle", ROOT / "scripts/verify_model_audit_bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.validate_audit_bundle
    monkeypatch.setattr(
        module, "validate_audit_bundle", lambda *a, **kw: original(*a, **kw, now=NOW)
    )
    code = module.main(
        [
            str(bundle.root),
            "--synthetic",
            "--expected-release-id",
            bundle.manifest["release"]["release_id"],
            "--expected-artifact-fingerprint",
            bundle.manifest["release"]["artifact_fingerprint"],
            "--expected-subject-hash",
            bundle.manifest["subject_hash"],
            "--expected-manifest-sha256",
            bundle.manifest_sha256,
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 2 and result["valid"] and not result["policy_satisfied"]


def test_manifest_seal_covers_evaluation_not_just_candidate(bundle):
    trusted_manifest_hash = bundle.manifest_sha256
    trusted_artifact_hash = bundle.manifest["release"]["artifact_fingerprint"]
    bundle.evaluation["run_id"] = "synthetic-replacement-eval"
    bundle.seal()
    assert bundle.manifest["release"]["artifact_fingerprint"] == trusted_artifact_hash
    blocked(
        bundle.check(expected_manifest_sha256=trusted_manifest_hash),
        "sealed_manifest_hash_mismatch",
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("excerpt", "evidence_excerpt_mismatch"),
        ("source_hash", "evidence_source_mismatch"),
        ("cutoff", "evidence_after_cutoff"),
        ("duplicate_record", "duplicate_subject_record"),
        ("target", "packet_target_mismatch"),
        ("context", "cross_stage_context_contamination"),
        ("failed_precheck", "frozen_packet_scope_invalid"),
        ("reclassify", "frozen_packet_scope_invalid"),
    ],
)
def test_semantic_packet_checks_even_after_all_hashes_rebound(bundle, mutation, code):
    if mutation == "excerpt":
        bundle.packet["evidence"][0]["excerpt"] = "SYNTHETIC changed excerpt"
    elif mutation == "source_hash":
        bundle.packet["evidence"][0]["source_sha256"] = "c" * 64
    elif mutation == "cutoff":
        bundle.packet["evidence"][0]["captured_at"] = "2026-09-30T04:00:00+00:00"
    elif mutation == "duplicate_record":
        bundle.subject["records"].append(copy.deepcopy(bundle.subject["records"][0]))
    elif mutation == "target":
        bundle.packet["subject"]["id"] = 9
    elif mutation == "context":
        bundle.packet["subject"]["generator_reasoning"] = "SYNTHETIC prior hidden context"
    elif mutation == "failed_precheck":
        bundle.packet["precheck"] = "failed"
    else:
        bundle.packet["data_classification"] = "official_public"
    bundle.rebind_packet()
    blocked(bundle.check(), code)


def test_nested_trace_model_fallback_cannot_hide_behind_correct_top_level_model(bundle):
    bundle.events["primary"][2]["item"]["actual_model_id"] = "weaker-model"
    bundle.save_trace("primary")
    bundle.seal()
    blocked(bundle.check(), "trace_model_mismatch")


def test_overlapping_workdirs_are_detectable_context_contamination(bundle):
    meta = bundle.executions["adversarial"]
    meta["cwd"] = bundle.executions["primary"]["cwd"] + "/child"
    for key, filename in (("schema_path", "schema.json"), ("response_path", "response.json")):
        previous = meta[key]
        meta[key] = meta["cwd"] + "/" + filename
        meta["argv"][meta["argv"].index(previous)] = meta[key]
    meta["argv_sha256"] = audit.object_sha256(meta["argv"])
    bundle.save_meta("adversarial")
    bundle.seal()
    blocked(bundle.check(), "cross_stage_context_reuse")


def test_arbitration_cannot_start_before_independent_reviews_complete(bundle):
    bundle.executions["arbitration"]["started_at"] = "2026-09-30T02:00:00+00:00"
    bundle.save_meta("arbitration")
    bundle.seal()
    blocked(bundle.check(), "arbitration_precedes_reviews")


def test_detect_mutation_during_validation(bundle, monkeypatch):
    original = audit._evaluation

    def racing_evaluation(*args):
        result = original(*args)
        (bundle.root / "release/data.json").write_bytes(b"SYNTHETIC concurrent mutation")
        return result

    monkeypatch.setattr(audit, "_evaluation", racing_evaluation)
    blocked(bundle.check(), "artifact_changed_during_validation")


def test_bounded_read_fails_closed(bundle, monkeypatch):
    monkeypatch.setattr(audit, "MAX_FILE_BYTES", 16)
    blocked(bundle.check(), "artifact_too_large")


def test_empty_code_snapshot_cannot_satisfy_release_binding(bundle):
    bundle.manifest["code"] = bundle.write("release/code.txt", b"")
    bundle.seal()
    blocked(bundle.check(), "release_artifact_empty")


@pytest.mark.parametrize(
    "field",
    [
        "prompt_sha256",
        "schema_sha256",
        "response_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "argv_sha256",
    ],
)
def test_metadata_hashes_must_match_actual_artifacts(bundle, field):
    bundle.executions["primary"][field] = "d" * 64
    bundle.save_meta("primary")
    bundle.seal()
    blocked(bundle.check())


def test_cli_without_external_expectations_cannot_self_approve(bundle):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_model_audit_bundle.py"), str(bundle.root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "independently supplied" in completed.stderr


@pytest.mark.parametrize("decision", [item.value for item in Decision])
def test_real_decision_enum_is_auditable_without_granting_business_approval(bundle, decision):
    for opinion in bundle.opinions.values():
        opinion["decision"] = decision
        opinion["conditions"] = ["SYNTHETIC only"] if decision == Decision.CONDITIONAL else []
    bundle.rebind_packet()
    result = bundle.check()
    assert result["status"] == "SYNTHETIC_VERIFIED"
    assert not result["policy_satisfied"] and not result["customer_output_allowed"]


@pytest.mark.parametrize("persistent", [False, True])
def test_native_session_identity_without_stdout_model_fields(bundle, persistent):
    for stage in bundle.manifest["stages"]:
        bundle.attach_runtime_identity(stage, persistent=persistent)
    bundle.seal()
    result = bundle.check()
    assert result["status"] == "SYNTHETIC_VERIFIED", result
    assert not result["policy_satisfied"] and not result["snapshot_pinned"]


@pytest.mark.parametrize(
    "mutation",
    [
        "model",
        "provider",
        "thread",
        "turn",
        "completion_turn",
        "run",
        "provenance_thread",
        "provenance_turn",
        "source",
        "old_capture",
        "future_capture",
        "old_session",
        "cwd",
        "effort",
        "inherited",
        "root_turn",
        "input",
        "response",
        "final_response",
        "missing_model",
        "missing_provider",
        "missing_input",
        "missing_context",
        "missing_completion",
        "multi_turn",
        "prior_user",
        "tool",
        "unknown",
        "fallback",
        "stdout_conflict",
    ],
)
def test_runtime_identity_rejects_untrusted_mismatched_or_incomplete_capture(bundle, mutation):
    bundle.attach_runtime_identity("adversarial")
    events = bundle.runtime_traces["adversarial"]
    capture = bundle.runtime_captures["adversarial"]
    if mutation == "model":
        events[2]["payload"]["model"] = "weaker-model"
    elif mutation == "provider":
        events[0]["payload"]["model_provider"] = "other"
    elif mutation == "thread":
        events[0]["payload"]["id"] = str(uuid4())
    elif mutation == "turn":
        events[2]["payload"]["turn_id"] = str(uuid4())
    elif mutation == "completion_turn":
        events[-1]["payload"]["turn_id"] = str(uuid4())
    elif mutation in {"run", "provenance_thread", "provenance_turn"}:
        field = {
            "run": "audit_id",
            "provenance_thread": "session_id",
            "provenance_turn": "turn_id",
        }[mutation]
        capture[field] = str(uuid4())
    elif mutation == "source":
        capture["source_basename"] = "../" + capture["source_basename"]
    elif mutation in {"old_capture", "future_capture"}:
        capture["captured_at"] = (
            "2026-09-30T00:00:00+00:00"
            if mutation == "old_capture"
            else "2026-10-01T00:00:00+00:00"
        )
    elif mutation == "old_session":
        events[0]["timestamp"] = "2026-09-29T00:00:00+00:00"
    elif mutation == "cwd":
        events[2]["payload"]["cwd"] = bundle.executions["primary"]["cwd"]
    elif mutation == "effort":
        events[2]["payload"]["effort"] = "low"
    elif mutation == "inherited":
        events[0]["payload"]["parent_thread_id"] = bundle.executions["primary"]["session_id"]
    elif mutation == "root_turn":
        events[2]["payload"]["root_turn_id"] = str(uuid4())
    elif mutation == "input":
        events[3]["payload"]["content"][0]["text"] += "\nSYNTHETIC previous opinion"
    elif mutation == "response":
        events[-1]["payload"]["last_agent_message"] = "SYNTHETIC stale result"
    elif mutation == "final_response":
        events[4]["payload"]["content"][0]["text"] = "SYNTHETIC unrelated final"
    elif mutation == "missing_model":
        del events[2]["payload"]["model"]
    elif mutation == "missing_provider":
        del events[0]["payload"]["model_provider"]
    elif mutation in {"missing_input", "missing_context", "missing_completion"}:
        events.pop({"missing_input": 3, "missing_context": 2, "missing_completion": -1}[mutation])
    elif mutation == "multi_turn":
        events.insert(2, copy.deepcopy(events[1]))
    elif mutation == "prior_user":
        events.insert(4, copy.deepcopy(events[3]))
    elif mutation == "tool":
        events[4]["payload"]["type"] = "function_call"
    elif mutation == "unknown":
        events[4]["type"] = "world_state"
    elif mutation == "fallback":
        events[2]["payload"]["fallback_used"] = True
    elif mutation == "stdout_conflict":
        bundle.events["adversarial"][1]["model"] = "weaker-model"
        bundle.save_trace("adversarial")
    bundle.save_runtime("adversarial")
    bundle.seal()
    blocked(bundle.check())


@pytest.mark.parametrize("artifact", ["runtime-session.jsonl", "runtime-capture.json"])
def test_missing_runtime_identity_artifacts_fail_closed(bundle, artifact):
    bundle.attach_runtime_identity("primary")
    bundle.seal()
    (bundle.root / "primary" / artifact).unlink()
    blocked(bundle.check())


def test_runtime_trace_hash_must_match_capture_receipt(bundle):
    bundle.attach_runtime_identity("primary")
    bundle.runtime_captures["primary"]["trace_sha256"] = "f" * 64
    bundle.manifest["stages"]["primary"]["runtime_identity"]["capture"] = bundle.write(
        "primary/runtime-capture.json",
        bundle.runtime_captures["primary"],
    )
    bundle.seal()
    blocked(bundle.check(), "runtime_capture_provenance_mismatch")


def test_other_stage_runtime_trace_cannot_supply_identity(bundle):
    bundle.attach_runtime_identity("primary")
    bundle.attach_runtime_identity("adversarial")
    bundle.manifest["stages"]["adversarial"]["runtime_identity"] = copy.deepcopy(
        bundle.manifest["stages"]["primary"]["runtime_identity"],
    )
    bundle.seal()
    blocked(bundle.check(), "runtime_capture_provenance_mismatch")


def test_non_ephemeral_execution_requires_complete_runtime_capture(bundle):
    meta = bundle.executions["primary"]
    meta["argv"].remove("--ephemeral")
    meta["argv_sha256"] = audit.object_sha256(meta["argv"])
    bundle.save_meta("primary")
    bundle.seal()
    blocked(bundle.check(), "execution_session_capture_required")


def test_native_session_accepts_emitted_user_event_instead_of_response_item(bundle):
    bundle.attach_runtime_identity("primary")
    event = bundle.runtime_traces["primary"][3]
    text = event["payload"]["content"][0]["text"]
    event.update(type="event_msg", payload={"type": "user_message", "message": text})
    bundle.save_runtime("primary")
    bundle.seal()
    assert bundle.check()["status"] == "SYNTHETIC_VERIFIED"


def test_runtime_prior_assistant_context_is_not_a_fresh_review(bundle):
    bundle.attach_runtime_identity("primary")
    events = bundle.runtime_traces["primary"]
    events.insert(1, copy.deepcopy(events[4]))
    bundle.save_runtime("primary")
    bundle.seal()
    blocked(bundle.check(), "runtime_prior_assistant_context")


def test_runtime_system_context_cannot_contain_primary_opinion(bundle):
    bundle.attach_runtime_identity("adversarial")
    events = bundle.runtime_traces["adversarial"]
    events.insert(
        1,
        {
            "type": "response_item",
            "timestamp": events[0]["timestamp"],
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": "SYNTHETIC prior opinion: "
                        + encode(bundle.opinions["primary"]).decode(),
                    }
                ],
            },
        },
    )
    bundle.save_runtime("adversarial")
    bundle.seal()
    blocked(bundle.check(), "cross_stage_prompt_contamination")


def test_runtime_turn_id_cannot_be_reused_between_stages(bundle):
    bundle.attach_runtime_identity("primary")
    bundle.attach_runtime_identity("adversarial")
    turn = bundle.runtime_captures["primary"]["turn_id"]
    bundle.runtime_captures["adversarial"]["turn_id"] = turn
    for event in bundle.runtime_traces["adversarial"]:
        for key in ("turn_id", "root_turn_id"):
            if key in event["payload"]:
                event["payload"][key] = turn
    bundle.save_runtime("adversarial")
    bundle.seal()
    blocked(bundle.check(), "cross_stage_runtime_turn_reuse")
