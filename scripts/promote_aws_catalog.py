"""Offline AWS promotion. Defaults to a physically read-only SQLite connection."""

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

from cloud_expert.pricing.aws_catalog_promotion import (
    apply_aws_catalog_promotion,
    prepare_aws_catalog_promotion,
)
from cloud_expert.pricing.official_catalog import CatalogSelection


def _write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, required=True, help="Explicit existing SQLite file"
    )
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=int)
    parser.add_argument("--policy-snapshot", type=int)
    parser.add_argument(
        "--selection", type=Path, help="JSON list of exact CatalogSelection objects"
    )
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--plan", type=Path)
    parser.add_argument(
        "--report-dir", type=Path, required=True, help="New immutable run directory"
    )
    parser.add_argument("--apply", action="store_true", help="Coordinator only; explicit commit")
    args = parser.parse_args()
    if args.apply and not args.plan:
        parser.error("--apply requires a saved --plan")
    if args.plan and any((args.snapshot, args.policy_snapshot, args.selection)):
        parser.error("saved plan cannot be combined with new selection inputs")
    if not args.plan and not all((args.snapshot, args.policy_snapshot, args.selection)):
        parser.error("--snapshot, --policy-snapshot and --selection are required")
    database = args.database.resolve(strict=True)
    if not database.is_file():
        parser.error("database must be an existing file")
    args.report_dir.mkdir(parents=True, exist_ok=False)
    uri = database.as_uri() + ("?mode=rw" if args.apply else "?mode=ro")
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True, timeout=10))

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: Any, _: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    with Session(engine) as session:
        try:
            now = datetime.now(UTC)
            plan = (
                json.loads(args.plan.read_text(encoding="utf-8-sig"))
                if args.plan
                else prepare_aws_catalog_promotion(
                    session,
                    snapshot_id=args.snapshot,
                    policy_snapshot_id=args.policy_snapshot,
                    selections=[
                        CatalogSelection.model_validate(row)
                        for row in json.loads(args.selection.read_text(encoding="utf-8-sig"))
                    ],
                    raw_root=args.raw_root,
                    as_of=now,
                    max_age_days=args.max_age_days,
                )
            )
            _write(args.report_dir / "plan.json", plan)
            result = apply_aws_catalog_promotion(
                session, plan, raw_root=args.raw_root, apply=args.apply, now=now
            )
            _write(args.report_dir / "proposal.json", result)
            if args.apply:
                session.commit()
                result["transaction_committed"] = True
            else:
                session.rollback()
            result["database_open_mode"] = "rw" if args.apply else "ro"
            result["network_requests"] = 0
            _write(args.report_dir / "result.json", result)
        except Exception as exc:
            session.rollback()
            _write(
                args.report_dir / "failure.json",
                {
                    "status": "blocked",
                    "error": str(exc),
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
