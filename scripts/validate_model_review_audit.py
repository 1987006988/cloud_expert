from __future__ import annotations

import json
from collections import Counter

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.session import SessionLocal


def main() -> int:
    with SessionLocal() as session:
        assignments = list(session.scalars(select(ModelReviewAssignment)))
        events = list(session.scalars(select(ModelReviewAuditEvent)))
    assignments_by_id = {row.id: row for row in assignments}
    events_by_assignment: Counter[int] = Counter(row.assignment_id for row in events)
    latest_event = {row.assignment_id: row for row in sorted(events, key=lambda row: row.id)}
    missing_event = [row.id for row in assignments if not events_by_assignment[row.id]]
    orphan_event = [row.id for row in events if row.assignment_id not in assignments_by_id]
    event_state_mismatch = [
        assignment_id
        for assignment_id, row in latest_event.items()
        if assignment_id in assignments_by_id
        and row.new_status != assignments_by_id[assignment_id].review_state
    ]
    duplicate_finding = len({row.precheck_finding_id for row in assignments}) != len(assignments)
    result = {
        "assignments": len(assignments),
        "audit_events": len(events),
        "states": dict(Counter(row.review_state for row in assignments)),
        "missing_audit_event": len(missing_event),
        "orphan_audit_event": len(orphan_event),
        "event_state_mismatch": len(event_state_mismatch),
        "duplicate_precheck_finding": duplicate_finding,
        "valid": not (missing_event or orphan_event or event_state_mismatch or duplicate_finding),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
