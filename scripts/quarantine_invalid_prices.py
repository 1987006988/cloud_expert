"""Offline deterministic quarantine. Default SQLite mode=ro; no price modifications."""

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

from cloud_expert.pricing.official_catalog import decode_catalog_json
from cloud_expert.pricing.price_quarantine import (
    QuarantinePlan,
    apply_price_quarantine,
    prepare_price_quarantine,
)


def _write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--price-ids", type=int, nargs="+")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if bool(args.plan) == bool(args.price_ids):
        parser.error("supply exactly one of --plan or --price-ids")
    if args.apply and (not args.plan or not args.expected_plan_sha256):
        parser.error("--apply requires a saved --plan and --expected-plan-sha256")
    database = args.database.resolve(strict=True)
    if not database.is_file():
        parser.error("database must be an existing SQLite file")
    args.report_dir.mkdir(parents=True, exist_ok=False)
    mode = "rw" if args.apply else "ro"
    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(
            database.as_uri() + f"?mode={mode}",
            uri=True,
            timeout=10,
        ),
    )

    @event.listens_for(engine, "connect")
    def safety(connection: Any, _: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        if not args.apply:
            connection.execute("PRAGMA query_only=ON")

    committed = False
    try:
        with Session(engine) as session:
            try:
                now = datetime.now(UTC)
                plan = (
                    QuarantinePlan.model_validate(decode_catalog_json(args.plan.read_bytes()))
                    if args.plan
                    else prepare_price_quarantine(
                        session,
                        args.price_ids,
                        raw_root=args.raw_root,
                        now=now,
                    )
                )
                _write(args.report_dir / "plan.json", plan.model_dump(mode="json"))
                result = apply_price_quarantine(
                    session,
                    plan,
                    expected_plan_sha256=args.expected_plan_sha256 or plan.plan_sha256,
                    raw_root=args.raw_root,
                    apply=args.apply,
                    now=now,
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
                _write(
                    args.report_dir / "failure.json",
                    {
                        "status": "blocked",
                        "error": str(exc),
                        "transaction_committed": committed,
                        "verify_database_before_retry": args.apply,
                        "customer_eligible": False,
                    },
                )
                raise
    finally:
        engine.dispose()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
