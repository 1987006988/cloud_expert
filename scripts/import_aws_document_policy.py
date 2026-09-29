"""Plan or append licensed AWS document Evidence; never approve prices."""

from __future__ import annotations

import argparse
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy.orm import Session

from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.aws_billing_policy import canonical, digest, evidence_row
from cloud_expert.pricing.aws_document_policy import RULE, prepare_document_policy


def prepare(session: Session, ids: list[int], root: Path, now: datetime) -> dict[str, Any]:
    if not ids or len(set(ids)) != len(ids) or session.new or session.dirty or session.deleted:
        raise ValueError("unique snapshot IDs and a clean session are required")
    plans = [
        prepare_document_policy(session, item, raw_root=root, as_of=now) for item in sorted(ids)
    ]
    content = {"rule_version": RULE, "documents": plans}
    return {**content, "plan_sha256": digest(canonical(content))}


def apply_plan(
    session: Session, ids: list[int], root: Path, now: datetime, expected: str
) -> dict[str, Any]:
    plan = prepare(session, ids, root, now)
    if plan["plan_sha256"] != expected:
        raise ValueError("fresh plan differs from reviewed input")
    created = 0
    existing = 0
    bindings = []
    for document in plan["documents"]:
        for record in document["records"]:
            row = evidence_row(session, record)
            if row is None:
                row = evidence_row(session, record, apply=True)
                created += 1
            else:
                existing += 1
            assert row is not None
            bindings.append(
                {
                    "snapshot_record_id": record["snapshot_record_id"],
                    "evidence_id": row.id,
                    "kind": record["kind"],
                    "scope": record["scope"],
                    "content_hash": row.content_hash,
                }
            )
    return {
        "plan_sha256": expected,
        "created_evidence": created,
        "existing_evidence": existing,
        "bindings": bindings,
        "price_approval": False,
        "tco_eligible": False,
        "customer_eligible": False,
        "review_required": True,
    }


def _write(path: Path, data: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", type=int, action="append", required=True)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if args.apply and not args.expected_plan_sha256:
        parser.error("--apply requires --expected-plan-sha256 from a prior dry run")
    args.report_dir.mkdir(parents=True, exist_ok=False)
    committed = False
    try:
        with SessionLocal() as session:
            with session.begin():
                now = datetime.now(UTC)
                plan = prepare(session, args.snapshot_id, args.raw_root, now)
                _write(args.report_dir / "plan.json", plan)
                if not args.apply:
                    print(json.dumps({"mode": "dry_run", "plan_sha256": plan["plan_sha256"]}))
                    return 0
                result = apply_plan(
                    session, args.snapshot_id, args.raw_root, now, args.expected_plan_sha256
                )
            committed = True
        result["database_commit_completed"] = True
        _write(args.report_dir / "result.json", result)
        print(json.dumps(result))
    except Exception as exc:
        failure = {"error_type": type(exc).__name__, "database_commit_completed": committed}
        with suppress(OSError):
            _write(args.report_dir / "failure.json", failure)
        print(json.dumps(failure))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
