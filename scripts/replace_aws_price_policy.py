"""Coordinator-only AWS policy replacement; default physically read-only preview."""

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

from cloud_expert.pricing.aws_price_replacement import (
    AWSReplacementPlan,
    apply_aws_price_replacement,
    prepare_aws_price_replacement,
)
from cloud_expert.pricing.official_catalog import decode_catalog_json


def _write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Existing SQLite file")
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--old-price", type=int, choices=(13, 17, 18))
    parser.add_argument("--document-plan", type=Path, help="One-SKU frozen document catalog plan")
    parser.add_argument("--plan", type=Path, help="Saved AWSReplacementPlan JSON")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument(
        "--report-dir", type=Path, required=True, help="New immutable run directory"
    )
    parser.add_argument("--apply", action="store_true", help="Coordinator only; explicit commit")
    args = parser.parse_args()
    if args.apply and (not args.plan or not args.expected_plan_sha256):
        parser.error("--apply requires --plan and --expected-plan-sha256")
    if args.plan and (args.old_price is not None or args.document_plan is not None):
        parser.error("saved plan cannot be combined with new-plan arguments")
    if not args.plan and (args.old_price is None or args.document_plan is None):
        parser.error("preview requires --old-price and --document-plan, or a saved --plan")
    database = args.database.resolve(strict=True)
    if not database.is_file():
        parser.error("database must be an existing file")
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
    try:
        with Session(engine) as session:
            try:
                at = datetime.now(UTC)
                if args.plan:
                    plan = AWSReplacementPlan.model_validate(
                        decode_catalog_json(args.plan.read_bytes())
                    )
                else:
                    plan = prepare_aws_price_replacement(
                        session,
                        old_price_id=args.old_price,
                        document_plan=decode_catalog_json(args.document_plan.read_bytes()),
                        raw_root=args.raw_root,
                        as_of=at,
                    )
                _write(args.report_dir / "plan.json", plan.model_dump(mode="json"))
                result = apply_aws_price_replacement(
                    session,
                    plan,
                    expected_plan_sha256=args.expected_plan_sha256 or plan.plan_sha256,
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
                _write(
                    args.report_dir / "failure.json",
                    {
                        "status": "blocked",
                        "error": str(exc),
                        "transaction_committed": committed,
                        "verify_database_before_retry": bool(args.apply),
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
