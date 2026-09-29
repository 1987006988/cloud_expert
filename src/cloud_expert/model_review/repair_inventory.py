"""Read-only, deterministic disposition proposals; never review approvals or writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models import model_review_workflow as _workflow  # noqa: F401
from cloud_expert.pricing import price_lifecycle

VERSION = "review_repair_inventory_v2"
SUBJECTS = (
    "review_item",
    "mapping_candidate",
    "candidate_decision_result",
    "comparability_assessment",
)
TABLES = SUBJECTS + (
    "price_snapshot",
    "model_review_run",
    "model_review_finding",
    "model_review_assignment",
    "model_review_audit_event",
    "parsed_field_candidate",
    "parsing_run",
    "evidence",
    "source_document",
    "snapshot_record",
    "mapping_candidate_evidence",
    "mapping_rule_set",
    "evidence_package",
    "tco_result",
    "decision_run",
    "normalized_specification",
    "normalization_run",
    "canonical_field_definition",
)
Row = dict[str, Any]
Inventory = dict[str, dict[int, Row]]
REBUILD_ORDER = [
    "parsing",
    "normalization",
    "comparability",
    "mapping",
    "evidence",
    "tco",
    "decision",
    "independent_model_review",
    "regression_evaluation",
]
NEXT_STEPS = {
    "validate_price_lifecycle": "Run the dedicated live lifecycle receipt validator against current prices, raw evidence and policy permissions; preserve history and grant no approval.",
    "preserve_history": "Retain terminal history; do not delete records or reuse old approvals.",
    "investigate_integrity": "Repair references from original evidence; rerun deterministic precheck.",
    "validate_replacement": "Verify successor against immutable source and unit/scope; record explicit supersession only after review.",
    "repair_parser": "Fix the parser with a regression case; reparse immutable source into a new version.",
    "collect_evidence": "Acquire scope-specific official evidence; keep missing facts unknown.",
    "verify_scope": "Verify qualifiers, market and scope against the original source; rebuild affected versions.",
    "rebuild_downstream": "Rebuild from current compatible dependencies and invalidate obsolete approvals through audited events.",
    "retain_limitation": "Record the limitation without converting unknown into unsupported or approved.",
    "independent_model_review": "Run fresh precheck, independent primary/adversarial review and arbitration if required.",
}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=True, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _parse_key(row: Row) -> tuple[Any, ...]:
    return tuple(
        row.get(key)
        for key in (
            "source_document_id",
            "snapshot_record_id",
            "target_table",
            "target_identity",
            "field_code",
        )
    )


def _numeric(value: Any) -> bool:
    try:
        return value is not None and Decimal(str(value)).is_finite()
    except InvalidOperation:
        return False


def _read(session: Session) -> Inventory:
    if session.new or session.dirty or session.deleted:
        raise ValueError("inventory requires a clean, read-only session")
    with session.no_autoflush:
        return {
            name: {
                int(row["id"]): dict(row)
                for row in session.execute(
                    select(Base.metadata.tables[name]).order_by(Base.metadata.tables[name].c.id)
                ).mappings()
            }
            for name in TABLES
        }


class _Planner:
    def __init__(self, data: Inventory):
        self.data = data
        self.latest: dict[tuple[str, int], Row] = {}
        runs = data["model_review_run"]
        for finding in sorted(
            data["model_review_finding"].values(), key=lambda r: (r["run_id"], r["id"])
        ):
            if (
                runs.get(finding["run_id"], {}).get("reviewer_model")
                == "deterministic_evidence_precheck"
            ):
                self.latest[(finding["subject_type"], finding["subject_id"])] = finding
        self.assignments: dict[tuple[str, int], list[Row]] = defaultdict(list)
        for row in data["model_review_assignment"].values():
            self.assignments[(row["target_type"], row["target_id"])].append(row)
        self.audit: dict[int, list[Row]] = defaultdict(list)
        for event in data["model_review_audit_event"].values():
            self.audit[event.get("assignment_id", -1)].append(event)
        self.parsed: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
        for row in data["parsed_field_candidate"].values():
            self.parsed[_parse_key(row)].append(row)
        self.links: dict[int, list[Row]] = defaultdict(list)
        for row in data["mapping_candidate_evidence"].values():
            self.links[row["mapping_candidate_id"]].append(row)
        self.packages: dict[int, list[Row]] = defaultdict(list)
        for row in data["evidence_package"].values():
            self.packages[row["mapping_candidate_id"]].append(row)
        self.normalized: dict[tuple[int, int], list[Row]] = defaultdict(list)
        for row in data["normalized_specification"].values():
            self.normalized[(row["product_id"], row["canonical_field_id"])].append(row)

    def evidence(self, evidence_id: int) -> Row:
        e = self.data["evidence"].get(evidence_id, {})
        s = self.data["source_document"].get(e.get("source_document_id", -1), {})
        snap = self.data["snapshot_record"].get(e.get("snapshot_record_id", -1), {})
        complete = bool(
            e
            and s
            and snap
            and snap.get("source_document_id") == s["id"]
            and s.get("content_hash")
            and snap.get("content_hash")
            and snap.get("content_hash") == s.get("content_hash")
            and snap.get("storage_path")
            and snap.get("manifest_path")
            and e.get("locator")
            and e.get("excerpt")
        )
        return {
            "evidence_id": evidence_id,
            "chain_complete": complete,
            "source_document_id": s.get("id"),
            "snapshot_record_id": snap.get("id"),
            "evidence_hash": _hash(e),
            "source_record_hash": _hash(s),
            "snapshot_record_hash": _hash(snap),
            "locator": e.get("locator"),
            "excerpt_hash": _hash(e.get("excerpt")),
            "recorded_source_content_hash": s.get("content_hash"),
            "recorded_snapshot_content_hash": snap.get("content_hash"),
            "captured_at": str(snap.get("captured_at")),
            "raw_file_verification": "required_before_disposition_not_performed_by_inventory",
        }

    def context(self, kind: str, row: Row, finding: Row, subject_id: int | None = None) -> Row:
        ctx: Row = {
            "subject": row,
            "precheck": finding,
            "evidence_ids": set(finding.get("evidence_ids", [])),
        }
        if kind == "price_snapshot":
            ctx["price_lifecycle"] = self.price_provenance(row, subject_id)
            if row.get("evidence_id") is not None:
                ctx["evidence_ids"].add(row["evidence_id"])
            for envelope in ctx["price_lifecycle"]["envelopes"]:
                for record in (envelope["assignment"], envelope["finding"]):
                    ctx["evidence_ids"].update(record.get("evidence_ids") or [])
                for successor in envelope["referenced_successor_rows"]:
                    if successor.get("evidence_id") is not None:
                        ctx["evidence_ids"].add(successor["evidence_id"])
        elif kind == "review_item":
            old = self.data["parsed_field_candidate"].get(
                row.get("parsed_field_candidate_id", -1), {}
            )
            versions = self.parsed.get(_parse_key(old), []) if old else []
            # A newer ID is only a replacement candidate, never proof of supersession.
            ctx["parsed"] = old
            ctx["replacement_candidates"] = [p for p in versions if p["id"] > old["id"]]
            ctx["parsing_runs"] = [
                self.data["parsing_run"].get(p["parsing_run_id"], {}) for p in versions
            ]
            for value in [row.get("evidence_id"), old.get("evidence_id")]:
                if value is not None:
                    ctx["evidence_ids"].add(value)
            for p in ctx["replacement_candidates"]:
                if p.get("evidence_id") is not None:
                    ctx["evidence_ids"].add(p["evidence_id"])
        elif kind in {"mapping_candidate", "candidate_decision_result"}:
            mapping = (
                row
                if kind == "mapping_candidate"
                else self.data["mapping_candidate"].get(row.get("mapping_candidate_id", -1), {})
            )
            ctx["mapping"] = mapping
            ctx["rule"] = self.data["mapping_rule_set"].get(mapping.get("rule_set_id", -1), {})
            ctx["packages"] = self.packages.get(mapping.get("id", -1), [])
            ctx["links"] = self.links.get(mapping.get("id", -1), [])
            ctx["evidence_ids"].update(link["evidence_id"] for link in ctx["links"])
            if kind == "candidate_decision_result":
                ctx["tco"] = self.data["tco_result"].get(row.get("tco_result_id", -1), {})
                ctx["decision_run"] = self.data["decision_run"].get(
                    row.get("decision_run_id", -1), {}
                )
        elif kind == "comparability_assessment":
            ctx["normalized"] = [
                n
                for product in (row.get("source_product_id", -1), row.get("target_product_id", -1))
                for n in self.normalized.get((product, row.get("canonical_field_id", -1)), [])
            ]
            ctx["evidence_ids"].update(n["evidence_id"] for n in ctx["normalized"])
        ctx["evidence_ids"] = sorted(ctx["evidence_ids"])
        ctx["evidence"] = [self.evidence(eid) for eid in ctx["evidence_ids"]]
        return ctx

    def price_provenance(self, row: Row, subject_id: int | None) -> Row:
        """Check envelope links only. Never substitute inventory for live receipt validation."""
        assignments = self.assignments.get(("price_snapshot", subject_id or row.get("id", -1)), [])
        envelopes, issues = [], []
        if len(assignments) != 1:
            issues.append("lifecycle_assignment_missing_or_ambiguous")
        for assignment in assignments:
            finding = self.data["model_review_finding"].get(
                assignment.get("precheck_finding_id", -1), {}
            )
            run = self.data["model_review_run"].get(assignment.get("precheck_run_id", -1), {})
            events = self.audit.get(assignment["id"], [])
            receipt = run.get("summary_json")
            receipt = receipt if isinstance(receipt, dict) else {}
            plan = receipt.get("plan")
            plan = plan if isinstance(plan, dict) else {}
            digest = run.get("input_fingerprint")
            if not (
                run.get("reviewer_model") == price_lifecycle.ACTOR
                and run.get("policy_version") == price_lifecycle.VERSION
                and isinstance(digest, str)
                and len(digest) == 64
                and all(c in "0123456789abcdef" for c in digest)
                and run.get("run_code") == price_lifecycle.RUN_PREFIX + digest
                and receipt.get("schema_version") == "price_replacement_receipt_v1"
                and plan.get("plan_sha256") == digest
                and receipt.get("receipt_sha256")
                and finding.get("run_id") == run.get("id")
                and finding.get("subject_type") == "price_snapshot"
                and finding.get("subject_id") == row.get("id")
                and finding.get("verdict") == "superseded_by_verified_price"
                and finding.get("reason_code") == price_lifecycle.VERSION
                and finding.get("rationale") == receipt.get("receipt_sha256")
                and assignment.get("input_hash") == finding.get("input_hash") == digest
                and assignment.get("evidence_ids") == finding.get("evidence_ids")
                and assignment.get("review_state") == "superseded"
            ):
                issues.append("lifecycle_envelope_binding_invalid")
            successors = []
            if len(events) != 1:
                issues.append("lifecycle_audit_missing_or_ambiguous")
            for event in events:
                records = event.get("affected_records")
                record = (
                    records[0]
                    if isinstance(records, list)
                    and len(records) == 1
                    and isinstance(records[0], dict)
                    else {}
                )
                successor_id = record.get("new_price_id")
                successor = (
                    self.data["price_snapshot"].get(successor_id, {})
                    if type(successor_id) is int
                    else {}
                )
                successors.append(successor)
                if not (
                    event.get("source") == price_lifecycle.EVENT_SOURCE
                    and event.get("reason") == price_lifecycle.VERSION
                    and event.get("model_id") is None
                    and event.get("new_status") == "superseded"
                    and event.get("previous_status") is None
                    and event.get("event_code")
                    == f"{price_lifecycle.RUN_PREFIX}{digest}:{row.get('id')}"
                    and event.get("downstream_rebuild_required") is True
                    and record.get("schema_version") == "price_replacement_event_v1"
                    and record.get("old_price_id") == row.get("id")
                    and record.get("plan_sha256") == digest
                    and record.get("receipt_sha256") == receipt.get("receipt_sha256")
                    and successor
                    and successor_id != row.get("id")
                    and record.get("price_sku_id")
                    == row.get("price_sku_id")
                    == successor.get("price_sku_id")
                ):
                    issues.append("lifecycle_audit_binding_invalid")
            envelopes.append(
                {
                    "assignment": assignment,
                    "finding": finding,
                    "run": run,
                    "audit_events": events,
                    "referenced_successor_rows": successors,
                }
            )
        return {
            "envelopes": envelopes,
            "structural_issues": sorted(set(issues)),
            "live_validation": "required_not_performed_by_inventory",
            "approval_granted": False,
        }

    def classify(self, kind: str, row: Row, ctx: Row) -> tuple[str, str]:
        if kind not in SUBJECTS and kind != "price_snapshot":
            return "unsupported_subject_type", "investigate_integrity"
        if not row:
            return "subject_missing", "investigate_integrity"
        if kind == "price_snapshot":
            if ctx["price_lifecycle"]["structural_issues"]:
                return "price_lifecycle_provenance_invalid", "investigate_integrity"
            if any(not e["chain_complete"] for e in ctx["evidence"]):
                return "evidence_chain_incomplete", "investigate_integrity"
            return "price_lifecycle_requires_live_validation", "validate_price_lifecycle"
        if row.get("superseded_by_id") is not None or row.get("candidate_status") == "superseded":
            return "historical_superseded", "preserve_history"
        if row.get("status") == "resolved":
            return "historical_resolved", "preserve_history"
        if any(not e["chain_complete"] for e in ctx["evidence"]):
            return "evidence_chain_incomplete", "investigate_integrity"
        if kind == "review_item":
            return self.classify_field(row, ctx)
        if kind == "mapping_candidate":
            blockers = row.get("blocking_reasons") or []
            if row.get("candidate_status") == "rejected":
                return "mapping_rejected", "preserve_history"
            if not ctx["evidence_ids"]:
                return "mapping_provenance_missing", "collect_evidence"
            if "missing_required_field" in blockers:
                return "mapping_required_fields_missing", "collect_evidence"
            if "family_category_mismatch" in blockers:
                return "mapping_category_mismatch", "verify_scope"
            if blockers or row.get("candidate_status") == "not_comparable":
                return "mapping_hard_block", "verify_scope"
            if ctx["rule"].get("market_mode") in {"cross_market", "cross_market_analysis"}:
                return "cross_market_research_only", "retain_limitation"
            return "mapping_source_verification", "independent_model_review"
        if kind == "candidate_decision_result":
            mapping = ctx["mapping"]
            if (
                mapping.get("superseded_by_id") is not None
                or mapping.get("candidate_status") == "superseded"
            ):
                return "decision_upstream_superseded", "rebuild_downstream"
            referenced = {
                s.get("evidence_package_id") for s in (row.get("key_strength_conditions") or [])
            }
            if any(
                p["id"] in referenced and p.get("superseded_by_id") is not None
                for p in ctx["packages"]
            ):
                return "decision_package_superseded", "rebuild_downstream"
            if row.get("hard_block_count", 0) or row.get("decision_status") == "blocked":
                return "decision_hard_block", "verify_scope"
            if row.get("decision_status") == "invalid_mapping" or not mapping:
                return "decision_invalid_mapping", "rebuild_downstream"
            if (
                row.get("decision_status") == "incomplete_cost"
                or ctx["tco"].get("completeness_status") != "complete"
            ):
                return "decision_cost_incomplete", "collect_evidence"
            if not ctx["evidence_ids"] or not any(
                p.get("superseded_by_id") is None and p.get("evidence_completeness") == 1
                for p in ctx["packages"]
            ):
                return "decision_evidence_incomplete", "collect_evidence"
            return "decision_source_verification", "independent_model_review"
        if kind == "comparability_assessment":
            by_spec: dict[int, set[str]] = defaultdict(set)
            for n in ctx["normalized"]:
                by_spec[n["product_specification_id"]].add(n["scope_type"])
            if row.get("reason_code") == "scope_mismatch" and any(
                len(scopes) > 1 for scopes in by_spec.values()
            ):
                return "normalization_version_scope_conflict", "rebuild_downstream"
            reason = row.get("reason_code")
            if reason in {"missing_one_side", "missing_both_sides"}:
                return "comparability_" + reason, "collect_evidence"
            if reason == "market_scope_differs":
                return "comparability_market_limitation", "retain_limitation"
            return "comparability_scope_verification", "verify_scope"
        return "unsupported_subject_type", "investigate_integrity"

    def classify_field(self, row: Row, ctx: Row) -> tuple[str, str]:
        old = ctx["parsed"]
        successors = ctx["replacement_candidates"]
        if successors:
            return "parse_replacement_requires_validation", "validate_replacement"
        if not old or not ctx["evidence_ids"]:
            return "field_provenance_missing", "investigate_integrity"
        field = row.get("field_code") or ""
        if field == "compute.memory_gib" and not _numeric(old.get("normalized_value")):
            return "memory_column_non_numeric", "repair_parser"
        if field == "compute.cpu_architecture":
            return "cpu_architecture_source_verification", "verify_scope"
        if field == "zone.name":
            return "zone_identity_availability_scope", "collect_evidence"
        if field == "sla.availability_percentage":
            return "sla_request_storage_scope", "repair_parser"
        if field.startswith("object_storage."):
            return "object_storage_scope_qualifier", "verify_scope"
        if old.get("review_status") == "rejected":
            return "rejected_parser_output", "repair_parser"
        return "field_source_verification", "independent_model_review"

    def plan(self) -> Row:
        subjects = set(self.latest) | set(self.assignments)
        for kind in SUBJECTS:
            for row in self.data[kind].values():
                if kind == "review_item" and row.get("status") == "resolved":
                    continue
                if (
                    kind == "comparability_assessment"
                    and row.get("review_status") != "pending_review"
                ):
                    continue
                subjects.add((kind, row["id"]))
        items = []
        for kind, subject_id in sorted(subjects):
            row = self.data.get(kind, {}).get(subject_id, {})
            finding = self.latest.get((kind, subject_id), {})
            ctx = self.context(kind, row, finding, subject_id)
            root, action = self.classify(kind, row, ctx)
            assignments = self.assignments.get((kind, subject_id), [])
            lifecycle = ctx.get("price_lifecycle")
            dedicated = lifecycle is not None and not lifecycle["structural_issues"]
            flags = []
            if lifecycle is not None:
                flags.append("price_lifecycle_live_validation_required")
                flags.extend(lifecycle["structural_issues"])
            if not finding and not dedicated:
                flags.append("missing_deterministic_precheck")
            if any(
                a["review_state"] in {"model_approved", "model_approved_with_conditions"}
                for a in assignments
            ):
                flags.append("existing_approval_requires_scope_and_version_validation")
            if finding and not any(a["precheck_finding_id"] == finding["id"] for a in assignments):
                flags.append("latest_precheck_unassigned")
            if not dedicated and any(
                a["precheck_finding_id"] != finding.get("id") for a in assignments
            ):
                flags.append("historical_precheck_assignments_retained")
            if any(
                a["precheck_finding_id"] == finding.get("id")
                and (
                    a["input_hash"] != finding.get("input_hash")
                    or sorted(a["evidence_ids"]) != sorted(finding.get("evidence_ids", []))
                    or a["precheck_run_id"] != finding.get("run_id")
                )
                for a in assignments
            ):
                flags.append("assignment_precheck_conflict")
            items.append(
                {
                    "subject_type": kind,
                    "subject_id": subject_id,
                    "root_cause": root,
                    "proposed_action": action,
                    "flags": flags,
                    "precheck_finding_id": finding.get("id"),
                    "precheck_run_code": self.data["model_review_run"]
                    .get(finding.get("run_id", -1), {})
                    .get("run_code"),
                    "input_hash": finding.get("input_hash"),
                    "precheck_verdict": finding.get("verdict"),
                    "precheck_reason_code": finding.get("reason_code"),
                    "assignment_ids": [a["id"] for a in assignments],
                    "assignment_states": [a["review_state"] for a in assignments],
                    **({"price_lifecycle": lifecycle} if lifecycle is not None else {}),
                    "evidence_ids": ctx["evidence_ids"],
                    "replacement_candidate_ids": [
                        p["id"] for p in ctx.get("replacement_candidates", [])
                    ],
                    "group_key": "/".join(
                        [
                            root,
                            str(row.get("provider_code") or "unspecified"),
                            str(row.get("field_code") or kind),
                        ]
                    ),
                    "preconditions": {
                        "subject_hash": _hash(row),
                        "dependency_hash": _hash(ctx),
                        "assignment_hash": _hash(assignments),
                        "requires_fresh_precheck": not dedicated,
                        **(
                            {"requires_live_price_lifecycle_validation": True}
                            if lifecycle is not None
                            else {}
                        ),
                        "requires_immutable_evidence_verification": True,
                        "requires_independent_review_for_fact_changes": True,
                        "requires_coordinator_transaction_and_audit": True,
                        "preserve_legacy_history": True,
                        "invalidate_changed_upstream_approvals_and_downstream": action
                        != "preserve_history",
                    },
                }
            )
        evidence_ids = sorted({eid for item in items for eid in item["evidence_ids"]})
        groups: dict[str, Row] = {}
        for item in items:
            key = item["group_key"]
            group = groups.setdefault(
                key,
                {
                    "count": 0,
                    "proposed_action": item["proposed_action"],
                    "next_step": NEXT_STEPS[item["proposed_action"]],
                    "sample_subjects": [],
                },
            )
            group["count"] += 1
            if len(group["sample_subjects"]) < 5:
                group["sample_subjects"].append(
                    {"type": item["subject_type"], "id": item["subject_id"]}
                )
        manifest: Row = {
            "schema_version": "1.0",
            "planner_version": VERSION,
            "dry_run": True,
            "database_writeback": False,
            "approvals_granted": 0,
            "gate_updated": False,
            "source_snapshot_hash": _hash(self.data),
            "selection_policy": "latest_deterministic_precheck_per_subject_by_run_id; preserve_all_assignments",
            "limits": [
                "Root causes are deterministic triage, not semantic model verdicts.",
                "Newer parsed candidates are not automatically accepted or marked superseding.",
                "Raw files and source freshness must be verified before any disposition.",
                "No executable write operations are included; no apply mode exists.",
                "Price lifecycle envelopes are not model reviews; receipt hashes, permissions and current consumability require the dedicated live validator.",
            ],
            "summary": {
                "subjects": len(items),
                "assignments": len(self.data["model_review_assignment"]),
                "audit_events_preserved": len(self.data["model_review_audit_event"]),
                "latest_precheck_subjects": len(self.latest),
                "root_cause_counts": dict(sorted(Counter(i["root_cause"] for i in items).items())),
                "subject_type_counts": dict(
                    sorted(Counter(i["subject_type"] for i in items).items())
                ),
                "flag_counts": dict(sorted(Counter(f for i in items for f in i["flags"]).items())),
                "assignment_state_counts": dict(
                    sorted(
                        Counter(
                            a["review_state"] for a in self.data["model_review_assignment"].values()
                        ).items()
                    )
                ),
            },
            "downstream_rebuild_order": REBUILD_ORDER,
            "groups": groups,
            "evidence": [self.evidence(eid) for eid in evidence_ids],
            "items": items,
        }
        manifest["plan_id"] = _hash(manifest)
        return manifest


def build_repair_inventory(session: Session) -> Row:
    """Describe all current and historical queue subjects without flushing or committing."""
    return _Planner(_read(session)).plan()


def validate_repair_plan(session: Session, manifest: Row) -> None:
    """Fail closed on any changed record or edited plan; this does not authorize writes."""
    current = build_repair_inventory(session)
    if _hash(current) != _hash(manifest):
        raise ValueError(
            "repair plan is stale or altered; regenerate from current evidence and queue"
        )


def inventory_from_sqlite(database: Path) -> Row:
    """Use OS-backed SQLite read-only mode and one consistent transaction."""
    uri = database.resolve().as_uri() + "?mode=ro"

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    engine = create_engine("sqlite://", creator=connect)
    try:
        with engine.connect() as connection:
            # Begin after dialect initialization, which may roll back a new connection.
            connection.exec_driver_sql("BEGIN")
            with Session(connection, autoflush=False) as session:
                return build_repair_inventory(session)
    finally:
        engine.dispose()
