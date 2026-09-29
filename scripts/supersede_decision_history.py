"""Plan or apply historical invalidation; no model calls or successor creation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.decision_supersession import (
    DecisionSupersessionPlan,
    apply_decision_supersession,
    plan_decision_supersession,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled deterministic Decision supersession")
    parser.add_argument("--plan", type=Path, help="Previously saved plan.json; required for apply")
    parser.add_argument("--result-id", action="append", type=int)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Coordinator only; commits one validated plan"
    )
    args = parser.parse_args()
    if args.apply and args.plan is None:
        parser.error("--apply requires a previously inspected --plan")
    if args.plan and args.result_id:
        parser.error("a saved plan cannot be combined with --result-id")
    args.report_dir.mkdir(parents=True, exist_ok=False)
    with SessionLocal() as session:
        try:
            plan = (
                DecisionSupersessionPlan.model_validate_json(
                    args.plan.read_text(encoding="utf-8-sig")
                )
                if args.plan
                else plan_decision_supersession(
                    session, result_ids=args.result_id, limit=args.limit
                )
            )
            (args.report_dir / "plan.json").write_text(
                plan.model_dump_json(indent=2), encoding="utf-8"
            )
            report = apply_decision_supersession(session, plan, apply=args.apply)
            (args.report_dir / "proposal.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            if args.apply:
                session.commit()
                report["transaction_committed"] = True
            else:
                session.rollback()
            (args.report_dir / "result.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
        except Exception:
            session.rollback()
            (args.report_dir / "failure.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "verify_database_before_retry": True,
                        "approvals_granted": 0,
                    }
                ),
                encoding="utf-8",
            )
            raise
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
