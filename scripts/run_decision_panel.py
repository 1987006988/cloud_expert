"""C11: local precheck by default; explicit isolated model review without DB writes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml
from sqlalchemy import text

from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.decision_panel import ROOT, run_decision_panel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument(
        "--execute-models",
        action="store_true",
        help="Explicitly permit paid model calls; report-only, never writeback.",
    )
    parser.add_argument(
        "--report-root", type=Path, default=ROOT / "reports/model_review/decision_panel"
    )
    args = parser.parse_args()
    authorization = yaml.safe_load(
        (ROOT / "config/model_review/review_authorization.yaml").read_text(encoding="utf-8")
    )
    with SessionLocal() as session:
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            session.execute(text("PRAGMA query_only = ON"))
        elif dialect == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        else:
            parser.error("Only SQLite and PostgreSQL read-only sessions are supported")
        try:
            result = run_decision_panel(
                session,
                args.candidate_id,
                args.report_root,
                execute_models=args.execute_models,
                authorization=authorization,
            )
        finally:
            session.rollback()
            if dialect == "sqlite":
                session.execute(text("PRAGMA query_only = OFF"))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"ready_not_executed", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
