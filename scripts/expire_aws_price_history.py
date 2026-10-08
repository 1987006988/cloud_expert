"""Record verified expired AWS history; default physically read-only preview."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from cloud_expert.pricing.aws_expired_history import (
    ExpiryConflict,
    ExpiryPlan,
    apply_expired_history,
    prepare_expired_history,
)
from cloud_expert.pricing.official_catalog import decode_catalog_json


def _write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--price-ids", nargs="+", type=int)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if bool(args.plan) == bool(args.price_ids):
        parser.error("provide --price-ids for complete pairs, or --plan, not both")
    if args.apply and not (args.plan and args.expected_plan_sha256):
        parser.error("--apply requires --plan and --expected-plan-sha256")
    database = args.database.resolve(strict=True)
    if not database.is_file():
        parser.error("existing SQLite file required")
    args.report_dir.mkdir(parents=True, exist_ok=False)
    mode = "rw" if args.apply else "ro"
    uri = database.as_uri() + f"?mode={mode}"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True, timeout=10))

    @event.listens_for(engine, "connect")
    def safety(connection: Any, _: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        if not args.apply:
            connection.execute("PRAGMA query_only=ON")

    committed = False
    result: dict[str, Any] = {}
    try:
        with Session(engine, autoflush=False) as session:
            try:
                at = datetime.now(UTC)
                plan = (
                    ExpiryPlan.model_validate(decode_catalog_json(args.plan.read_bytes()))
                    if args.plan
                    else prepare_expired_history(
                        session, args.price_ids, raw_root=args.raw_root, now=at
                    )
                )
                _write(args.report_dir / "plan.json", plan.model_dump(mode="json"))
                result = apply_expired_history(
                    session,
                    plan,
                    expected_hash=args.expected_plan_sha256 or plan.plan_sha256,
                    raw_root=args.raw_root,
                    apply=args.apply,
                    now=at,
                )
                _write(args.report_dir / "proposal.json", result)
                if args.apply:
                    session.commit()
                    committed = True
                else:
                    session.rollback()
                result.update(
                    transaction_committed=committed, database_open_mode=mode, network_requests=0
                )
                _write(args.report_dir / "result.json", result)
            except Exception as exc:
                session.rollback()
                result = {
                    "status": "blocked",
                    "reason": str(exc) if isinstance(exc, ExpiryConflict) else type(exc).__name__,
                    "transaction_committed": committed,
                    "verify_database_before_retry": bool(args.apply),
                    "customer_eligible": False,
                }
                _write(args.report_dir / "failure.json", result)
                print(json.dumps(result))
                return 1
    finally:
        engine.dispose()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
