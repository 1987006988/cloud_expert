"""Controlled, append-only Decision panel overlay. No model calls or Gate changes.

The coordinator must review a dry-run plan, then supply its hash to apply in a
fresh transaction. The caller owns commit/rollback. Consumers must use
``current_internal_decision_approval`` on EVERY use, not cache DecisionReview.
Native traces remain local artifacts; raw opinion responses and execution
receipts are retained in the database. Alias identity is NOT a release Gate.
The report apply deadline is separate from the approval consumption lifetime.
The latter has a 24-hour INTERNAL ENGINEERING cap, not an owner policy claim.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import yaml
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionReview
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.model_review import decision_panel as panel
from cloud_expert.model_review import reproducibility as audit
from cloud_expert.model_review.isolated_runtime import RuntimeIsolationError, verify_local_artifact
from cloud_expert.model_review.registry import load_registry, resolve_model
from cloud_expert.model_review.schemas import Decision

VERSION = "decision_writeback.v2"
APPROVAL_MAX_AGE_SECONDS = 86400
APPROVAL_LIFETIME_BASIS = "internal_engineering_cap"
SOURCE = "decision_panel_writeback"
TARGET = "candidate_decision_result"
STAGES = ("primary", "adversarial", "arbitration")
CONFIG = panel.ROOT / "config/model_review"


class DecisionWritebackConflict(ValueError):
    """Sanitized fail-closed code; caller must not retry in a stale transaction."""


def _require(condition: object, code: str) -> None:
    if not condition:
        raise DecisionWritebackConflict(code)


def _now(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    _require(value.tzinfo is not None, "aware_clock_required")
    return value.astimezone(UTC)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _clean(session: Session) -> None:
    _require(not (session.new or session.dirty or session.deleted), "clean_session_required")


def _row(row: Any) -> dict[str, Any]:
    result = {column.key: getattr(row, column.key) for column in inspect(type(row)).columns}
    return {
        key: panel._utc(value).isoformat() if isinstance(value, datetime) else value
        for key, value in result.items()
    }


def _policies(summary: dict[str, Any]) -> None:
    policy = (CONFIG / "reproducibility_policy.yaml").read_bytes()
    audit._policy(policy)
    _require(_sha(policy) == summary.get("reproducibility_policy_sha256"), "policy_changed")
    registry = CONFIG / "model_registry.yaml"
    _require(_sha(registry.read_bytes()) == summary.get("registry_sha256"), "registry_changed")
    models, _ = load_registry(registry)
    resolution = resolve_model(models, verified_available={panel.MODEL_ID}, allow_fallback=False)
    _require(
        resolution.status == "AVAILABLE"
        and resolution.model is not None
        and resolution.model.model_id == panel.MODEL_ID
        and resolution.model.provider == "openai"
        and resolution.model.structured_output_supported,
        "highest_model_policy_changed",
    )
    auth = yaml.safe_load((CONFIG / "review_authorization.yaml").read_text(encoding="utf-8"))
    _require(
        isinstance(auth, dict)
        and panel._hash(auth) == summary.get("authorization_sha256")
        and auth.get("external_data_transfer_approved") is True
        and auth.get("approved_model") == panel.MODEL_ID
        and {"official_source_excerpts", "necessary_identifiers"}
        <= set(auth.get("approved_payload_classes", [])),
        "review_authorization_changed",
    )


def _stage(
    reader: audit._Reader,
    name: panel.Stage,
    packet: panel.DecisionPacket,
    prior: list[panel.DecisionOpinion],
    now: datetime,
) -> tuple[panel.DecisionOpinion, audit.ExecutionMetadata, audit.StageArtifacts, str]:
    refs = audit.StageArtifacts.model_validate(audit._json(reader.read(f"{name}/artifacts.json")))
    expected_paths = {
        "template": "template.txt",
        "prompt": "prompt.txt",
        "schema": "schema.json",
        "response": "response.raw.json",
        "execution": "execution.json",
        "trace": "stdout.jsonl",
        "stderr": "stderr.txt",
    }
    serialized = refs.model_dump(by_alias=True)
    for field, filename in expected_paths.items():
        _require(serialized[field]["path"] == f"{name}/{filename}", "stage_path_mismatch")
    _require(refs.runtime_identity is not None, "native_identity_required")
    assert refs.runtime_identity is not None
    _require(
        refs.runtime_identity.trace.path == f"{name}/runtime.native.jsonl"
        and refs.runtime_identity.capture.path == f"{name}/runtime.capture.json",
        "stage_path_mismatch",
    )
    meta = audit.ExecutionMetadata.model_validate(audit._json(reader.ref(refs.execution)))
    prompt = reader.ref(refs.prompt).decode("utf-8")
    raw = reader.ref(refs.response)
    schema = audit._json(reader.ref(refs.output_schema))
    _require(
        meta.stage == name
        and meta.prompt_version == panel.PROMPT_VERSION
        and meta.input_fingerprint == packet.fingerprint
        and meta.fallback_used is False
        and meta.exit_code == 0
        and audit._time(packet.checked_at)
        <= audit._time(meta.started_at)
        <= audit._time(meta.completed_at)
        <= now,
        "execution_binding_invalid",
    )
    _require(
        prompt == panel._prompt(name, packet, prior)
        and reader.ref(refs.template).decode("utf-8") == prompt.split("\nINPUT_JSON:\n", 1)[0]
        and schema == panel.DecisionOpinion.model_json_schema()
        and meta.prompt_sha256 == _sha(prompt.encode("utf-8"))
        and meta.schema_sha256 == panel._hash(schema)
        and meta.response_sha256 == _sha(raw)
        and meta.stdout_sha256 == _sha(reader.ref(refs.trace))
        and meta.stderr_sha256 == _sha(reader.ref(refs.stderr)),
        "execution_artifact_mismatch",
    )
    # Reuse native identity and contamination checks, never trust requested -m alone.
    audit._argv(meta, has_runtime_identity=True, require_isolation=True)
    audit._runtime_identity(
        reader, refs.runtime_identity, meta, prompt, raw, now.isoformat(), require_isolation=True
    )
    try:
        verify_local_artifact(reader.path(refs.runtime_identity.trace.path))
    except RuntimeIsolationError:
        raise DecisionWritebackConflict("runtime_artifact_permissions_invalid") from None
    audit._trace(reader.ref(refs.trace), raw, meta, runtime_identity_verified=True)
    privacy = audit._json(reader.read(f"{name}/privacy.json"))
    _require(
        privacy.get("status") == "passed"
        and privacy.get("finding_codes") == []
        and privacy.get("local_only") is True
        and privacy.get("transmit_to_model") is False
        and privacy.get("identity_verified") is True
        and privacy.get("isolated_home_used") is True
        and privacy.get("raw_trace_sha256") == refs.runtime_identity.trace.sha256,
        "privacy_receipt_invalid",
    )
    for value in (
        raw,
        reader.ref(refs.trace),
        reader.ref(refs.stderr),
    ):
        _require(not panel._runtime_sensitivity(value), "sensitive_artifact_rejected")
    _require(
        not panel._runtime_sensitivity(
            reader.ref(refs.runtime_identity.trace), verified_isolated_native=True
        ),
        "sensitive_artifact_rejected",
    )
    audit._json(raw)  # Duplicate keys/NaN must not be silently accepted by the opinion parser.
    opinion = panel.validate_opinion(raw.decode("utf-8"), packet, name)
    _require(
        opinion.model_dump(mode="json") == audit._json(reader.read(f"{name}/response.json")),
        "parsed_response_mismatch",
    )
    return opinion, meta, refs, raw.decode("utf-8")


def _validate_report(
    report_dir: Path,
    now: datetime,
    *,
    applied_at: datetime | None = None,
) -> tuple[dict[str, Any], audit._Reader]:
    # Only the consumer supplies applied_at, after validating all five persisted
    # rows. New plans and apply (including retries) always use the current clock.
    panel._unlinked_path(report_dir.absolute() / "manifest.json")
    reader = audit._Reader(report_dir)
    manifest_raw = reader.read("manifest.json")
    manifest = audit._json(manifest_raw)
    hashes = manifest.get("artifact_sha256")
    _require(isinstance(hashes, dict) and bool(hashes), "manifest_missing")
    assert isinstance(hashes, dict)
    actual = {p.relative_to(reader.root).as_posix() for p in reader.root.rglob("*") if p.is_file()}
    _require(actual == set(hashes) | {"manifest.json"}, "artifact_set_changed")
    for name, digest in hashes.items():
        _require(isinstance(digest, str) and len(digest) == 64, "artifact_digest_invalid")
        reader.read(name, digest)
    _require(
        manifest.get("version") == panel.PROMPT_VERSION
        and manifest.get("artifact_set_sha256") == panel._hash(hashes)
        and all(
            manifest.get(key) is False
            for key in ("customer_eligible", "database_writeback", "snapshot_pinned")
        )
        and all(
            manifest.get(key) is True
            for key in (
                "alias_may_change",
                "release_evaluation_required",
                "runtime_artifacts_local_only",
            )
        ),
        "manifest_contract_invalid",
    )
    summary = audit._json(reader.read("summary.json"))
    _require(
        summary.get("status") == "completed"
        and summary.get("target_type") == TARGET
        and type(summary.get("target_id")) is int
        and summary["target_id"] > 0
        and summary.get("run_id") == manifest.get("audit_run_id")
        and all(
            summary.get(key) is False
            for key in (
                "customer_eligible",
                "database_writeback",
                "aggregate_gate_updated",
                "model_version_gate_passed",
            )
        )
        and all(
            summary.get(key) is True
            for key in (
                "model_calls_executed",
                "model_calls_attempted",
                "availability_probe_executed",
                "alias_may_change",
                "revalidation_required_before_writeback",
            )
        )
        and summary.get("model_id") == panel.MODEL_ID
        and summary.get("model_version") == "alias_unresolved",
        "panel_not_completed",
    )
    checked = audit._time(summary["checked_at"])
    expires = audit._time(summary["report_expires_at"])
    validation_at = applied_at if applied_at is not None else now
    _require(
        checked <= validation_at <= now
        and validation_at < expires
        and expires < checked + timedelta(minutes=65),
        "report_not_fresh",
    )
    _policies(summary)
    resolution = audit._json(reader.read("model_resolution.json"))
    _require(
        resolution.get("status") == "AVAILABLE"
        and resolution.get("model_id") == panel.MODEL_ID
        and resolution.get("provider") == "openai"
        and resolution.get("fallback_used") is False
        and resolution.get("snapshot_pinned") is False
        and resolution.get("probe", {}).get("available") is True,
        "model_resolution_invalid",
    )
    payload = audit._json(reader.read("input.json"))
    fingerprint = audit._json(reader.read("fingerprint.json"))
    _require(
        fingerprint.get("public_payload_sha256")
        == panel._hash(
            {key: value for key, value in payload.items() if key != "input_fingerprint"}
        ),
        "public_payload_changed",
    )
    digest = panel._hash(fingerprint)
    _require(
        digest
        == manifest.get("input_fingerprint")
        == summary.get("input_fingerprint")
        == payload.get("input_fingerprint")
        and payload.get("target_id") == summary["target_id"]
        and payload.get("data_classification") == "official_public"
        and payload.get("review_scope") == summary.get("review_scope") == panel.SCOPED_REVIEW
        and payload.get("limitations") == summary.get("limitations")
        and set(panel.SCOPED_LIMITATIONS) <= set(payload.get("limitations", [])),
        "packet_scope_or_fingerprint_invalid",
    )
    packet = panel.DecisionPacket(
        panel._json(payload), panel._json(fingerprint), digest, summary["checked_at"]
    )
    opinions: list[panel.DecisionOpinion] = []
    executions: dict[str, audit.ExecutionMetadata] = {}
    refs_by_stage: dict[str, audit.StageArtifacts] = {}
    retained: dict[str, Any] = {}
    names = [item.get("stage") for item in summary["stages"]]
    _require(names in [list(STAGES[:2]), list(STAGES)], "panel_stages_invalid")
    stage_files = {
        "template.txt",
        "prompt.txt",
        "schema.json",
        "response.raw.json",
        "response.json",
        "execution.json",
        "stdout.jsonl",
        "stderr.txt",
        "runtime.native.jsonl",
        "runtime.capture.json",
        "privacy.json",
        "artifacts.json",
    }
    _require(
        set(hashes)
        == {"summary.json", "input.json", "fingerprint.json", "model_resolution.json"}
        | {f"{name}/{filename}" for name in names for filename in stage_files},
        "unexpected_artifacts",
    )
    for name in names:
        opinion, meta, refs, raw = _stage(
            reader, name, packet, opinions if name == "arbitration" else [], validation_at
        )
        opinions.append(opinion)
        executions[name], refs_by_stage[name] = meta, refs
        retained[name] = {
            "raw_response": raw,
            "opinion": opinion.model_dump(mode="json"),
            "execution": meta.model_dump(),
            "artifacts": refs.model_dump(by_alias=True),
        }
    _require(
        [m.model_dump() for m in executions.values()] == summary["stages"],
        "stage_receipts_mismatch",
    )
    disagreement = (
        opinions[0].decision != opinions[1].decision
        or opinions[0].conditions != opinions[1].conditions
    )
    _require(not disagreement or len(opinions) == 3, "arbitration_missing")
    # This structural adapter supplies only stages to the shared independence validator;
    # it is NOT an AuditBundle or a release-evaluation approval.
    audit._independence(
        reader, cast(Any, SimpleNamespace(stages=SimpleNamespace(**refs_by_stage))), executions
    )
    decision = panel.resolve_panel_opinions(
        opinions[0], opinions[1], opinions[2] if len(opinions) == 3 else None
    )
    _require(decision.value == summary["final_decision"], "resolution_mismatch")
    conditions = sorted({condition for opinion in opinions for condition in opinion.conditions})
    if decision in panel.APPROVALS:
        _require(set(conditions) <= set(panel.SCOPED_LIMITATIONS), "unenforceable_conditions")
    receipt = {
        "version": VERSION,
        "report_dir": str(reader.root),
        "manifest_sha256": _sha(manifest_raw),
        "artifact_set_sha256": manifest["artifact_set_sha256"],
        "run_id": summary["run_id"],
        "target_id": summary["target_id"],
        "input_fingerprint": digest,
        "review_scope": panel.SCOPED_REVIEW,
        "decision": decision.value,
        "report_expires_at": expires.isoformat(),
        "expires_at": (checked + timedelta(seconds=APPROVAL_MAX_AGE_SECONDS)).isoformat(),
        "approval_max_age_seconds": APPROVAL_MAX_AGE_SECONDS,
        "approval_lifetime_basis": APPROVAL_LIFETIME_BASIS,
        "explicit_validity_bounds": [],
        "checked_at": checked.isoformat(),
        "evidence_ids": sorted({e for opinion in opinions for e in opinion.evidence_references}),
        "conditions": conditions,
        "limitations": payload["limitations"],
        "stages": retained,
        "model_id": panel.MODEL_ID,
        "model_version": "alias_unresolved",
        "customer_eligible": False,
        "human_review": False,
        "rank_authorized": False,
        "model_version_gate_passed": False,
        "aggregate_gate_updated": False,
    }
    reader.unchanged()
    return receipt, reader


def _history(
    session: Session, target_id: int, *, exclude: tuple[int, int, int] | None = None
) -> str:
    assignments = list(
        session.scalars(
            select(ModelReviewAssignment)
            .where(
                ModelReviewAssignment.target_type == TARGET,
                ModelReviewAssignment.target_id == target_id,
            )
            .order_by(ModelReviewAssignment.id)
        )
    )
    events = list(
        session.scalars(
            select(ModelReviewAuditEvent)
            .where(ModelReviewAuditEvent.assignment_id.in_([row.id for row in assignments]))
            .order_by(ModelReviewAuditEvent.id)
        )
    )
    reviews = list(
        session.scalars(
            select(DecisionReview)
            .where(DecisionReview.candidate_result_id == target_id)
            .order_by(DecisionReview.id)
        )
    )
    excluded = exclude or (None, None, None)
    groups: tuple[list[Any], list[Any], list[Any]] = (assignments, events, reviews)
    return panel._hash(
        [
            [_row(row) for row in rows if row.id != ignored]
            for rows, ignored in zip(groups, excluded, strict=True)
        ]
    )


@dataclass(frozen=True)
class DecisionWritebackPlan:
    """Immutable, parent-reviewable proposal, not an approval authorization."""

    receipt_json: str
    prior_history_sha256: str

    @property
    def receipt(self) -> dict[str, Any]:
        return audit._json(self.receipt_json.encode("utf-8"))

    @property
    def plan_sha256(self) -> str:
        return panel._hash(
            {"receipt": self.receipt, "prior_history_sha256": self.prior_history_sha256}
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "plan_sha256": self.plan_sha256,
            "prior_history_sha256": self.prior_history_sha256,
            "receipt": self.receipt,
            "apply_performed": False,
            "parent_review_required": True,
        }


def _event_code(receipt: dict[str, Any]) -> str:
    return "decision-panel:" + str(receipt["manifest_sha256"])


def _scope(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        key: receipt[key]
        for key in (
            "review_scope",
            "version",
            "input_fingerprint",
            "manifest_sha256",
            "expires_at",
            "report_expires_at",
            "approval_max_age_seconds",
            "approval_lifetime_basis",
            "explicit_validity_bounds",
            "limitations",
            "conditions",
            "model_id",
            "model_version",
            "customer_eligible",
            "human_review",
            "rank_authorized",
            "model_version_gate_passed",
            "aggregate_gate_updated",
        )
    }


def _review_status(receipt: dict[str, Any]) -> str:
    if Decision(receipt["decision"]) in panel.APPROVALS:
        return "internally_approved"
    return "machine_generated" if receipt["decision"] == Decision.INCONCLUSIVE.value else "rejected"


def _existing(
    session: Session, receipt: dict[str, Any]
) -> tuple[ModelReviewAuditEvent, dict[str, Any]] | None:
    _require(
        receipt.get("version") == VERSION
        and receipt.get("approval_max_age_seconds") == APPROVAL_MAX_AGE_SECONDS
        and receipt.get("approval_lifetime_basis") == APPROVAL_LIFETIME_BASIS,
        "receipt_lifecycle_version_invalid",
    )
    events = list(
        session.scalars(
            select(ModelReviewAuditEvent).where(
                ModelReviewAuditEvent.event_code == _event_code(receipt)
            )
        )
    )
    _require(len(events) <= 1, "duplicate_writeback_receipt")
    if not events:
        return None
    event = events[0]
    _require(len(event.affected_records) == 1, "writeback_receipt_changed")
    stored = event.affected_records[0]
    _require(stored.get("receipt") == receipt, "writeback_receipt_changed")
    assignment = session.get(ModelReviewAssignment, event.assignment_id)
    _require(assignment is not None, "writeback_receipt_changed")
    assert assignment is not None
    finding = session.get(ModelReviewFinding, assignment.precheck_finding_id)
    run = session.get(ModelReviewRun, assignment.precheck_run_id)
    review = session.get(DecisionReview, stored.get("decision_review_id"))
    _require(all(row is not None for row in (finding, run, review)), "writeback_receipt_changed")
    assert review is not None and finding is not None and run is not None
    _require(
        stored.get("record_hashes")
        == {
            type(row).__tablename__: panel._hash(_row(row))
            for row in (run, finding, assignment, review)
        }
        and assignment.target_type == TARGET
        and assignment.target_id == receipt["target_id"]
        and assignment.review_state == receipt["decision"]
        and assignment.input_hash == receipt["input_fingerprint"]
        and finding.run_id == run.id == assignment.precheck_run_id
        and finding.subject_type == TARGET
        and finding.subject_id == receipt["target_id"]
        and finding.input_hash == receipt["input_fingerprint"]
        and finding.verdict == "ready_for_model_review"
        and finding.reason_code == "live_decision_packet_revalidated"
        and run.run_code == "decision_packet_" + receipt["manifest_sha256"]
        and run.policy_version == VERSION
        and run.reviewer_model == "deterministic_decision_packet_validation"
        and run.input_fingerprint == receipt["input_fingerprint"]
        and run.summary_json
        == {
            "source": SOURCE,
            "plan_sha256": stored["plan_sha256"],
            "model_calls_executed_by_writeback": False,
            "customer_eligible": False,
        }
        and event.source == SOURCE
        and event.model_id == panel.MODEL_ID
        and event.previous_status == "pending_model_review"
        and event.new_status == receipt["decision"]
        and event.reason == "Verified independent model panel; internal bounded cost only"
        and event.downstream_rebuild_required is True
        and review.candidate_result_id == receipt["target_id"]
        and review.reviewer == "model:" + panel.MODEL_ID
        and review.decision == _review_status(receipt)
        and review.approved_scope == _scope(receipt)
        and review.notes == panel._json(receipt)
        and review.expiration_date is not None
        and panel._utc(review.expiration_date) == audit._time(receipt["expires_at"])
        and panel._utc(review.reviewed_at)
        == panel._utc(event.timestamp)
        == panel._utc(run.reviewed_at)
        == panel._utc(assignment.created_at)
        == panel._utc(assignment.updated_at)
        and audit._time(receipt["checked_at"])
        <= panel._utc(event.timestamp)
        < audit._time(receipt["report_expires_at"])
        and panel._utc(event.timestamp) < audit._time(receipt["expires_at"]),
        "writeback_receipt_changed",
    )
    saved_plan = DecisionWritebackPlan(panel._json(receipt), stored["prior_history_sha256"])
    _require(saved_plan.plan_sha256 == stored["plan_sha256"], "stored_plan_changed")
    # Detect new pending work as well as later dispositions or edited historical reviews.
    _require(
        _history(session, receipt["target_id"], exclude=(assignment.id, event.id, review.id))
        == stored["prior_history_sha256"],
        "review_history_changed",
    )
    return event, stored


def _live(
    session: Session,
    receipt: dict[str, Any],
    raw_root: Path | None,
    now: datetime,
) -> dict[str, Any]:
    packet = panel.build_decision_packet(session, receipt["target_id"], raw_root=raw_root, now=now)
    _require(packet.fingerprint == receipt["input_fingerprint"], "current_input_changed")
    _require(packet.payload.get("review_scope") == panel.SCOPED_REVIEW, "current_scope_changed")
    # These are typed, fingerprint-bound DB fields, never dates inferred from prose.
    # Follow normalized facts to their source specifications, which hold valid_to.
    manifest = audit._json(packet.manifest_json.encode("utf-8"))
    models = {mapper.class_.__tablename__: mapper.class_ for mapper in Base.registry.mappers}
    bounds: dict[tuple[str, int, str], dict[str, Any]] = {}
    for record in manifest["records"]:
        model = models.get(record["table"])
        _require(model is not None, "validity_model_missing")
        assert model is not None
        row = session.get(model, record["id"])
        _require(row is not None and panel._row_digest(row) == record, "validity_input_changed")
        assert row is not None
        rows = [row]
        if record["table"] == "normalized_specification":
            source = row.product_specification
            _require(source is not None, "source_fact_missing")
            rows.append(source)
        for item in rows:
            digest = panel._row_digest(item)
            for field in (
                "valid_to",
                "effective_to",
                "expiration_date",
                "valid_until",
                "expires_at",
            ):
                deadline = getattr(item, field, None)
                if deadline is None:
                    continue
                _require(isinstance(deadline, datetime), "invalid_explicit_validity")
                key = (digest["table"], digest["id"], field)
                bounds[key] = {
                    **digest,
                    "field": field,
                    "expires_at": panel._utc(deadline).isoformat(),
                }
    explicit_bounds = [bounds[key] for key in sorted(bounds)]
    expires = min(
        [audit._time(receipt["checked_at"]) + timedelta(seconds=APPROVAL_MAX_AGE_SECONDS)]
        + [audit._time(bound["expires_at"]) for bound in explicit_bounds]
    )
    _require(now < expires, "approval_expired")
    return {
        **receipt,
        "expires_at": expires.isoformat(),
        "explicit_validity_bounds": explicit_bounds,
    }


def plan_decision_panel(
    session: Session,
    report_dir: Path,
    *,
    raw_root: Path | None = None,
    now: datetime | None = None,
) -> DecisionWritebackPlan:
    """Read-only validation; rebuild live dependencies, preserve existing history."""
    _clean(session)
    session.expire_all()
    current = _now(now)
    receipt, reader = _validate_report(report_dir, current)
    receipt = _live(session, receipt, raw_root, current)
    existing = _existing(session, receipt)
    prior = (
        existing[1]["prior_history_sha256"] if existing else _history(session, receipt["target_id"])
    )
    reader.unchanged()
    return DecisionWritebackPlan(panel._json(receipt), prior)


def _append(session: Session, plan: DecisionWritebackPlan, now: datetime) -> None:
    receipt = plan.receipt
    result = session.get(CandidateDecisionResult, receipt["target_id"])
    _require(result is not None, "subject_missing")
    assert result is not None
    run = ModelReviewRun(
        run_code="decision_packet_" + receipt["manifest_sha256"],
        policy_version=VERSION,
        reviewer_model="deterministic_decision_packet_validation",
        input_fingerprint=receipt["input_fingerprint"],
        reviewed_at=now,
        summary_json={
            "source": SOURCE,
            "plan_sha256": plan.plan_sha256,
            "model_calls_executed_by_writeback": False,
            "customer_eligible": False,
        },
    )
    session.add(run)
    session.flush()
    finding = ModelReviewFinding(
        run_id=run.id,
        subject_type=TARGET,
        subject_id=result.id,
        verdict="ready_for_model_review",
        reason_code="live_decision_packet_revalidated",
        rationale="Deterministic current packet validation",
        evidence_ids=receipt["evidence_ids"],
        input_hash=receipt["input_fingerprint"],
    )
    session.add(finding)
    session.flush()
    assignment = ModelReviewAssignment(
        precheck_run_id=run.id,
        precheck_finding_id=finding.id,
        target_type=TARGET,
        target_id=result.id,
        input_hash=receipt["input_fingerprint"],
        prior_review_status=result.review_status,
        review_state=receipt["decision"],
        evidence_ids=receipt["evidence_ids"],
        created_at=now,
        updated_at=now,
    )
    review = DecisionReview(
        candidate_result_id=result.id,
        reviewer="model:" + panel.MODEL_ID,
        reviewed_at=now,
        decision=_review_status(receipt),
        notes=panel._json(receipt),
        approved_scope=_scope(receipt),
        expiration_date=audit._time(receipt["expires_at"]),
    )
    session.add_all([assignment, review])
    session.flush()
    session.refresh(review)  # Include server-created timestamp in integrity receipt.
    session.add(
        ModelReviewAuditEvent(
            assignment_id=assignment.id,
            event_code=_event_code(receipt),
            previous_status="pending_model_review",
            new_status=receipt["decision"],
            source=SOURCE,
            model_id=panel.MODEL_ID,
            reason="Verified independent model panel; internal bounded cost only",
            affected_records=[
                {
                    "receipt": receipt,
                    "decision_review_id": review.id,
                    "prior_history_sha256": plan.prior_history_sha256,
                    "plan_sha256": plan.plan_sha256,
                    "record_hashes": {
                        type(row).__tablename__: panel._hash(_row(row))
                        for row in (run, finding, assignment, review)
                    },
                }
            ],
            downstream_rebuild_required=True,
            timestamp=now,
        )
    )
    session.flush()


def apply_decision_panel(
    session: Session,
    plan: DecisionWritebackPlan,
    *,
    apply: bool = False,
    parent_reviewed_plan_sha256: str | None = None,
    raw_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Default dry-run. Apply is atomic/idempotent; no commit, no business-result edits.

    Apply requires a fresh transaction. PostgreSQL uses SERIALIZABLE and a target
    lock; SQLite reserves its writer before reads. On ANY conflict the caller
    must roll back and replan. The parent hash binds reviewed inputs, not a claim
    of human approval or authorization for production/customer delivery.
    """
    _clean(session)
    current = _now(now)
    if apply:
        _require(parent_reviewed_plan_sha256 == plan.plan_sha256, "parent_plan_review_required")
        _require(not session.in_transaction(), "fresh_apply_transaction_required")
        dialect = session.get_bind().dialect.name
        _require(dialect in {"sqlite", "postgresql"}, "unsupported_write_dialect")
        if dialect == "postgresql":
            session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
        else:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    session.expire_all()

    def execute() -> bool:
        if apply:
            session.execute(
                select(CandidateDecisionResult)
                .where(CandidateDecisionResult.id == plan.receipt["target_id"])
                .with_for_update()
            ).scalar_one()
        receipt, reader = _validate_report(Path(plan.receipt["report_dir"]), current)
        receipt = _live(session, receipt, raw_root, current)
        _require(receipt == plan.receipt, "reviewed_report_changed")
        existing = _existing(session, receipt)
        if existing:
            _require(existing[1]["plan_sha256"] == plan.plan_sha256, "reviewed_plan_changed")
        else:
            _require(
                _history(session, receipt["target_id"]) == plan.prior_history_sha256,
                "review_history_changed",
            )
            if apply:
                _append(session, plan, current)
        reader.unchanged()
        return existing is not None

    if apply:
        with session.begin_nested():
            already = execute()
        session.expire_all()
    else:
        already = execute()
    return {
        "version": VERSION,
        "plan_sha256": plan.plan_sha256,
        "applied": apply,
        "already_applied": already,
        "records_appended": 5 if apply and not already else 0,
        "transaction_committed": False,
        "customer_eligible": False,
        "human_review": False,
        "rank_authorized": False,
        "aggregate_gate_updated": False,
        "downstream_revalidation_required": True,
    }


def current_internal_decision_approval(
    session: Session,
    candidate_id: int,
    *,
    scope: str,
    raw_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Fail closed on each use. Never consume this overlay for rank or customer output.

    Revalidates sealed artifacts, retained responses, current identity policy,
    expiry, review history and ALL live packet dependencies without writes.
    """
    _clean(session)
    session.expire_all()
    if scope != panel.SCOPED_REVIEW:
        return None
    review = session.scalar(
        select(DecisionReview)
        .where(DecisionReview.candidate_result_id == candidate_id)
        .order_by(DecisionReview.id.desc())
        .limit(1)
    )
    if review is None or review.decision != "internally_approved":
        return None
    try:
        current = _now(now)
        stored = audit._json((review.notes or "").encode("utf-8"))
        existing = _existing(session, stored)
        _require(existing is not None, "approval_audit_missing")
        assert existing is not None
        applied_at = panel._utc(existing[0].timestamp)
        _require(applied_at <= current < audit._time(stored["expires_at"]), "approval_expired")
        receipt, reader = _validate_report(
            Path(stored["report_dir"]), current, applied_at=applied_at
        )
        receipt = _live(session, receipt, raw_root, current)
        _require(receipt == stored and stored["target_id"] == candidate_id, "stored_review_changed")
        _require(Decision(stored["decision"]) in panel.APPROVALS, "not_approved")
        reader.unchanged()
        return {
            "decision_review_id": review.id,
            **_scope(stored),
            "evidence_ids": stored["evidence_ids"],
            "revalidated_at": current.isoformat(),
        }
    except (ValueError, OSError, KeyError, TypeError):
        return None
