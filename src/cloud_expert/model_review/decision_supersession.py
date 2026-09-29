"""Controlled historical Decision invalidation, never approval or recomputation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models.decision import DecisionRun
from cloud_expert.database.models.model_review_workflow import ModelReviewAuditEvent
from cloud_expert.decision import pipeline as engine

VERSION: Literal["decision_supersession_v1"] = "decision_supersession_v1"
TARGET = "candidate_decision_result"
SOURCE = "deterministic_supersession"
REASON = "concrete_newer_result_same_scenario_and_mapping"
Row = dict[str, Any]


class SupersessionConflict(ValueError):
    """No partial apply is allowed; replan from current state after a conflict."""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class SupersessionItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    old_snapshot: dict[str, Any]
    old_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    new_snapshot: dict[str, Any]
    new_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    assignments: tuple[dict[str, Any], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_binding(self) -> SupersessionItem:
        if _hash(self.old_snapshot) != self.old_hash or _hash(self.new_snapshot) != self.new_hash:
            raise ValueError("subject snapshot hash mismatch")
        old, new = self.old_snapshot["decision"], self.new_snapshot["decision"]
        if (
            old["id"] == new["id"]
            or old["mapping_candidate_id"] != new["mapping_candidate_id"]
            or self.old_snapshot["run"]["scenario_id"] != self.new_snapshot["run"]["scenario_id"]
            or old["decision_run_id"] >= new["decision_run_id"]
        ):
            raise ValueError("successor must be a higher run in the same scenario and mapping")
        ids = [item["assignment"]["id"] for item in self.assignments]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate assignment binding")
        return self


class DecisionSupersessionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["decision_supersession_v1"] = VERSION
    planned_at: str
    items: tuple[SupersessionItem, ...]
    skipped: tuple[dict[str, Any], ...]
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def check_manifest(self) -> DecisionSupersessionPlan:
        at = datetime.fromisoformat(self.planned_at)
        if at.tzinfo is None:
            raise ValueError("planning time must have an explicit timezone")
        if _hash(self.model_dump(exclude={"plan_sha256"})) != self.plan_sha256:
            raise ValueError("plan hash mismatch")
        old_ids = [item.old_snapshot["decision"]["id"] for item in self.items]
        new_ids = {item.new_snapshot["decision"]["id"] for item in self.items}
        if len(old_ids) != len(set(old_ids)) or set(old_ids) & new_ids:
            raise ValueError("duplicate or chained targets in one plan")
        return self


def _rows(
    session: Session, table_name: str, *, filters: dict[str, Any] | None = None, lock: bool = False
) -> list[Row]:
    table = Base.metadata.tables[table_name]
    query = select(table).order_by(table.c.id)
    for key, value in (filters or {}).items():
        query = query.where(table.c[key] == value)
    if lock:
        query = query.with_for_update()
    return [dict(row) for row in session.execute(query).mappings()]


def _one(session: Session, table: str, record_id: int, *, lock: bool = False) -> Row:
    rows = _rows(session, table, filters={"id": record_id}, lock=lock)
    if len(rows) != 1:
        raise SupersessionConflict(f"missing_record:{table}:{record_id}")
    return rows[0]


def _subject(
    session: Session, result_id: int, *, lock: bool = False, bind_review: bool = False
) -> Row:
    decision = _one(session, TARGET, result_id, lock=lock)
    run = _one(session, "decision_run", decision["decision_run_id"], lock=lock)
    snapshot: Row = {"decision": decision, "run": run}
    for name, key in (
        ("dimension_score", "candidate_result_id"),
        ("rule_evaluation", "candidate_result_id"),
        ("decision_review", "candidate_result_id"),
    ):
        rows = _rows(session, name, filters={key: result_id}, lock=lock)
        snapshot[name] = {"count": len(rows), "sha256": _hash(rows)}
    if bind_review:
        assignments = _rows(
            session,
            "model_review_assignment",
            filters={"target_type": TARGET, "target_id": result_id},
            lock=lock,
        )
        snapshot["review_workflow_sha256"] = _hash(
            [_assignment(session, row, lock=lock) for row in assignments]
        )
    return cast(Row, _jsonable(snapshot))


def _assignment(
    session: Session, row: Row, *, exclude_code: str | None = None, lock: bool = False
) -> Row:
    finding = _one(session, "model_review_finding", row["precheck_finding_id"], lock=lock)
    precheck = _one(session, "model_review_run", row["precheck_run_id"], lock=lock)
    if (
        finding["run_id"] != row["precheck_run_id"]
        or finding["subject_type"] != row["target_type"]
        or finding["subject_id"] != row["target_id"]
        or finding["input_hash"] != row["input_hash"]
        or set(finding["evidence_ids"]) != set(row["evidence_ids"])
        or precheck["reviewer_model"] != "deterministic_evidence_precheck"
    ):
        raise SupersessionConflict("assignment_precheck_integrity_mismatch")
    events = [
        event
        for event in _rows(
            session, "model_review_audit_event", filters={"assignment_id": row["id"]}, lock=lock
        )
        if event["event_code"] != exclude_code
    ]
    return cast(
        Row,
        _jsonable(
            {
                "assignment": row,
                "finding": finding,
                "precheck_run": precheck,
                "audit_history_sha256": _hash(events),
            }
        ),
    )


def _newest_run(session: Session, scenario_id: int, now: datetime) -> tuple[int | None, str | None]:
    runs = list(
        session.scalars(
            select(DecisionRun)
            .where(
                DecisionRun.scenario_id == scenario_id,
                DecisionRun.status.in_(["succeeded", "partial"]),
            )
            .order_by(DecisionRun.id.desc())
        )
    )
    if not runs:
        return None, "no_completed_run"
    run = runs[0]
    scenario, policy = run.scenario, run.policy
    if (
        scenario.status != "active"
        or scenario.deprecated_at is not None
        or policy.status != "active"
        or policy.deprecated_at is not None
        or scenario.scoring_policy_id != policy.id
        or run.scenario_version != scenario.scenario_version
        or run.policy_version != policy.policy_version
        or any(
            _utc(value) > now
            for value in (
                run.generated_at,
                run.mapping_cutoff,
                run.evidence_cutoff,
                run.price_cutoff,
            )
        )
        or any(
            value is not None and _utc(value) > now
            for value in (scenario.effective_from, policy.effective_from)
        )
    ):
        return None, "newest_run_not_current"
    candidates = list(session.scalars(engine._candidate_query(scenario)))
    if run.content_hash != engine._dependency_fingerprint(session, scenario, policy, candidates):
        return None, "newest_run_dependencies_outdated"
    return run.id, None


def _successor(
    session: Session, old: Row, newest_id: int | None, now: datetime
) -> tuple[Row | None, str | None]:
    row = old["decision"]
    if row["decision_status"] == "superseded" or row["superseded_by_id"] is not None:
        return None, "already_historical"
    if row["valid_to"] is not None and datetime.fromisoformat(row["valid_to"]) <= now:
        return None, "already_expired"
    if row["valid_from"] is not None and datetime.fromisoformat(row["valid_from"]) > now:
        return None, "old_result_not_yet_valid"
    if newest_id is None or row["decision_run_id"] >= newest_id:
        return None, "no_newer_eligible_run"
    candidates = _rows(
        session,
        TARGET,
        filters={"decision_run_id": newest_id, "mapping_candidate_id": row["mapping_candidate_id"]},
    )
    if len(candidates) != 1:
        return None, "no_concrete_successor"
    new = candidates[0]
    run = session.get(DecisionRun, newest_id)
    if run is None or row["mapping_candidate_id"] not in {
        candidate.id for candidate in session.scalars(engine._candidate_query(run.scenario))
    }:
        return None, "successor_mapping_not_current"
    if (
        new["decision_status"] == "superseded"
        or new["superseded_by_id"] is not None
        or new["valid_from"] is None
        or _utc(new["valid_from"]) > now
        or new["valid_to"] is not None
        and _utc(new["valid_to"]) <= now
    ):
        return None, "successor_not_current"
    if (row["provider_id"], row["entity_type"], row["entity_id"]) != (
        new["provider_id"],
        new["entity_type"],
        new["entity_id"],
    ):
        return None, "successor_target_identity_mismatch"
    return _subject(session, new["id"], bind_review=True), None


def plan_decision_supersession(
    session: Session,
    *,
    result_ids: list[int] | None = None,
    limit: int = 200,
    now: datetime | None = None,
) -> DecisionSupersessionPlan:
    """Read-only bounded plan. No successor or approval is ever synthesized."""
    _clean(session)
    if limit < 1 or limit > 1000:
        raise ValueError("plan limit must be between 1 and 1000")
    now = _utc(now or datetime.now(UTC))
    session.expire_all()
    items: list[SupersessionItem] = []
    skipped: list[Row] = []
    with session.no_autoflush:
        rows = _rows(session, TARGET)
        wanted = set(result_ids) if result_ids is not None else None
        if wanted is not None:
            skipped.extend(
                {"result_id": value, "reason": "missing_result"}
                for value in sorted(wanted - {row["id"] for row in rows})
            )
            rows = [row for row in rows if row["id"] in wanted]
        newest: dict[int, tuple[int | None, str | None]] = {}
        for row in rows:
            old = _subject(session, row["id"])
            scenario_id = old["run"]["scenario_id"]
            if scenario_id not in newest:
                newest[scenario_id] = _newest_run(session, scenario_id, now)
            run_id, reason = newest[scenario_id]
            successor, successor_reason = _successor(session, old, run_id, now)
            reason = reason or successor_reason
            if reason is None:
                assignments = _rows(
                    session,
                    "model_review_assignment",
                    filters={"target_type": TARGET, "target_id": row["id"]},
                )
                if not assignments:
                    reason = "missing_review_assignment"
                elif any(assignment["review_state"] == "superseded" for assignment in assignments):
                    reason = "assignment_already_superseded_conflict"
                else:
                    try:
                        bindings = tuple(
                            _assignment(session, assignment) for assignment in assignments
                        )
                    except SupersessionConflict as exc:
                        reason = str(exc)
            if reason is None and len(items) >= limit:
                reason = "plan_limit_reached"
            if reason is not None:
                skipped.append({"result_id": row["id"], "reason": reason})
                continue
            assert successor is not None
            items.append(
                SupersessionItem(
                    old_snapshot=old,
                    old_hash=_hash(old),
                    new_snapshot=successor,
                    new_hash=_hash(successor),
                    assignments=bindings,
                )
            )
    data = {
        "version": VERSION,
        "planned_at": now.isoformat(),
        "items": [item.model_dump() for item in items],
        "skipped": skipped,
    }
    return DecisionSupersessionPlan.model_validate({**data, "plan_sha256": _hash(data)})


def _clean(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        raise SupersessionConflict("clean_coordinator_session_required")


def _event_code(item: SupersessionItem) -> str:
    return f"{VERSION}:{item.old_snapshot['decision']['id']}:{item.new_snapshot['decision']['id']}:{_hash(item.model_dump())[:24]}"


def _affected(item: SupersessionItem, plan: DecisionSupersessionPlan) -> list[Row]:
    return [
        {
            "target_type": TARGET,
            "target_id": item.old_snapshot["decision"]["id"],
            "subject_hash": item.old_hash,
            "successor_id": item.new_snapshot["decision"]["id"],
            "successor_subject_hash": item.new_hash,
            "scenario_id": item.old_snapshot["run"]["scenario_id"],
            "mapping_candidate_id": item.old_snapshot["decision"]["mapping_candidate_id"],
            "plan_sha256": plan.plan_sha256,
            "customer_eligibility_granted": False,
        }
    ]


def _check_item(
    session: Session,
    item: SupersessionItem,
    plan: DecisionSupersessionPlan,
    now: datetime,
    *,
    lock: bool,
    current_runs: dict[int, tuple[int | None, str | None]],
) -> bool:
    old_id, new_id = item.old_snapshot["decision"]["id"], item.new_snapshot["decision"]["id"]
    old, new = (
        _subject(session, old_id, lock=lock),
        _subject(session, new_id, lock=lock, bind_review=True),
    )
    if _hash(new) != item.new_hash:
        raise SupersessionConflict(f"successor_snapshot_changed:{new_id}")
    scenario_id = old["run"]["scenario_id"]
    if scenario_id not in current_runs:
        current_runs[scenario_id] = _newest_run(session, scenario_id, now)
    newest, reason = current_runs[scenario_id]
    if reason or newest != new["decision"]["decision_run_id"]:
        raise SupersessionConflict(reason or "newer_run_appeared")
    rows = _rows(
        session,
        "model_review_assignment",
        filters={"target_type": TARGET, "target_id": old_id},
        lock=lock,
    )
    if {row["id"] for row in rows} != {binding["assignment"]["id"] for binding in item.assignments}:
        raise SupersessionConflict("assignment_set_changed")
    code = _event_code(item)
    existing = {
        row["assignment_id"]: row
        for row in _rows(
            session, "model_review_audit_event", filters={"event_code": code}, lock=lock
        )
    }
    if existing:
        if set(existing) != {row["id"] for row in rows}:
            raise SupersessionConflict("partial_or_foreign_audit_receipt")
        stamp = _utc(next(iter(existing.values()))["timestamp"]).isoformat()
        expected = json.loads(json.dumps(item.old_snapshot))
        expected["decision"].update(
            decision_status="superseded",
            valid_to=stamp,
            superseded_by_id=new_id,
            customer_eligible=False,
        )
        if old != expected:
            raise SupersessionConflict("already_applied_subject_changed")
        for row, binding in zip(rows, item.assignments, strict=True):
            event = existing[row["id"]]
            if (
                event["source"] != SOURCE
                or event["model_id"] is not None
                or event["previous_status"] != binding["assignment"]["review_state"]
                or event["new_status"] != "superseded"
                or event["reason"] != REASON
                or _utc(event["timestamp"]).isoformat() != stamp
                or not event["downstream_rebuild_required"]
                or event["affected_records"] != _affected(item, plan)
            ):
                raise SupersessionConflict("audit_receipt_changed")
            expected_assignment = json.loads(json.dumps(binding))
            expected_assignment["assignment"].update(review_state="superseded", updated_at=stamp)
            if _assignment(session, row, exclude_code=code, lock=lock) != expected_assignment:
                raise SupersessionConflict("already_applied_assignment_changed")
        return True
    if _hash(old) != item.old_hash:
        raise SupersessionConflict(f"old_subject_snapshot_changed:{old_id}")
    successor, reason = _successor(session, old, newest, now)
    if reason or successor != new:
        raise SupersessionConflict(reason or "successor_mismatch")
    for row, binding in zip(rows, item.assignments, strict=True):
        if row["review_state"] == "superseded" or _assignment(session, row, lock=lock) != binding:
            raise SupersessionConflict("assignment_snapshot_changed")
    return False


def _write_item(
    session: Session, item: SupersessionItem, plan: DecisionSupersessionPlan, now: datetime
) -> None:
    old, new = item.old_snapshot["decision"], item.new_snapshot["decision"]
    table = Base.metadata.tables[TARGET]
    result = session.execute(
        update(table)
        .where(
            table.c.id == old["id"],
            table.c.decision_run_id == old["decision_run_id"],
            table.c.mapping_candidate_id == old["mapping_candidate_id"],
            table.c.decision_status == old["decision_status"],
            table.c.superseded_by_id.is_(None),
        )
        .values(
            decision_status="superseded",
            valid_to=now,
            superseded_by_id=new["id"],
            customer_eligible=False,
        )
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise SupersessionConflict("decision_compare_and_set_failed")
    assignments = Base.metadata.tables["model_review_assignment"]
    for binding in item.assignments:
        row = binding["assignment"]
        changed = session.execute(
            update(assignments)
            .where(
                assignments.c.id == row["id"],
                assignments.c.review_state == row["review_state"],
                assignments.c.input_hash == row["input_hash"],
            )
            .values(review_state="superseded", updated_at=now)
        )
        if changed.rowcount != 1:  # type: ignore[attr-defined]
            raise SupersessionConflict("assignment_compare_and_set_failed")
        session.add(
            ModelReviewAuditEvent(
                assignment_id=row["id"],
                event_code=_event_code(item),
                previous_status=row["review_state"],
                new_status="superseded",
                source=SOURCE,
                model_id=None,
                reason=REASON,
                affected_records=_affected(item, plan),
                downstream_rebuild_required=True,
                timestamp=now,
            )
        )


def apply_decision_supersession(
    session: Session,
    plan: DecisionSupersessionPlan,
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> Row:
    """Validate all before writes. Atomic savepoint; coordinator owns outer commit.

    SQLite reserves the writer before reading; PostgreSQL locks scenario, subject,
    run and review rows. A caller must retry lock/deadlock failures from a fresh
    transaction, never continue after a conflict with a stale proposal.
    """
    _clean(session)
    plan = DecisionSupersessionPlan.model_validate(plan.model_dump())
    now = _utc(now or datetime.now(UTC))
    if datetime.fromisoformat(plan.planned_at) > now:
        raise SupersessionConflict("plan_from_future")
    session.expire_all()
    if apply:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            driver = connection.connection.driver_connection
            if not driver.in_transaction:  # type: ignore[union-attr]
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name != "postgresql":
            raise SupersessionConflict("unsupported_write_dialect")
    already: list[bool] = []

    def execute() -> None:
        current_runs: dict[int, tuple[int | None, str | None]] = {}
        if apply:
            for scenario_id in sorted(
                {item.old_snapshot["run"]["scenario_id"] for item in plan.items}
            ):
                _one(session, "decision_scenario", scenario_id, lock=True)
        with session.no_autoflush:
            already.extend(
                _check_item(session, item, plan, now, lock=apply, current_runs=current_runs)
                for item in plan.items
            )
        if apply:
            for item, done in zip(plan.items, already, strict=True):
                if not done:
                    _write_item(session, item, plan, now)
            session.flush()

    if apply:
        with session.begin_nested():
            execute()
        session.expire_all()
    else:
        execute()
    return {
        "version": VERSION,
        "plan_sha256": plan.plan_sha256,
        "applied": apply,
        "planned": len(plan.items),
        "already_applied": sum(already),
        "would_supersede": len(plan.items) - sum(already),
        "superseded": len(plan.items) - sum(already) if apply else 0,
        "audit_events_created": sum(
            len(item.assignments)
            for item, done in zip(plan.items, already, strict=True)
            if not done
        )
        if apply
        else 0,
        "skipped": len(plan.skipped),
        "skip_reasons": dict(Counter(row["reason"] for row in plan.skipped)),
        "successors_created": 0,
        "approvals_granted": 0,
        "customer_eligibility_granted": False,
        "transaction_committed": False,
    }
