"""Validate a panel report; apply only an explicitly parent-reviewed plan hash.

No model calls. Dry-run is database read-only. Apply commits one internal review
overlay only; the parent must authorize the target DB separately. This command
does not grant production, customer output, rank, human approval or Gate access.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.decision_writeback import apply_decision_panel, plan_decision_panel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--parent-reviewed-plan-sha256")
    args = parser.parse_args()
    if args.apply and not args.parent_reviewed_plan_sha256:
        parser.error("--apply requires --parent-reviewed-plan-sha256 from a reviewed dry-run")
    with SessionLocal() as session:
        dialect = session.get_bind().dialect.name
        if dialect not in {"sqlite", "postgresql"}:
            parser.error("Only SQLite and PostgreSQL are supported")
        try:
            session.execute(
                text(
                    "PRAGMA query_only = ON" if dialect == "sqlite" else "SET TRANSACTION READ ONLY"
                )
            )
            plan = plan_decision_panel(session, args.report_dir)
            session.rollback()
            if dialect == "sqlite":
                session.execute(text("PRAGMA query_only = OFF"))
                session.rollback()
            if not args.apply:
                result = plan.as_dict()
            else:
                result = apply_decision_panel(
                    session,
                    plan,
                    apply=True,
                    parent_reviewed_plan_sha256=args.parent_reviewed_plan_sha256,
                )
                session.commit()
                result["transaction_committed"] = True
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        except (ValueError, OSError, KeyError, TypeError, SQLAlchemyError):
            session.rollback()
            print(json.dumps({"status": "blocked", "reason": "decision_panel_validation_failed"}))
            return 1
        finally:
            session.rollback()
            if dialect == "sqlite":
                session.execute(text("PRAGMA query_only = OFF"))
                session.rollback()


if __name__ == "__main__":
    raise SystemExit(main())
