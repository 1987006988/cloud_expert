from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT as _ROOT  # noqa: F401
from check_week09_gate import check_week09_gate

from cloud_expert.database.session import SessionLocal
from cloud_expert.decision.pipeline import run_decision_engine
from cloud_expert.decision.reporting import write_decision_reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-code", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-dir", type=Path, help="New immutable directory for this run")
    args = parser.parse_args()
    if args.report_dir is not None:
        args.report_dir.mkdir(parents=True, exist_ok=False)
    gate = check_week09_gate()
    if args.report_dir is not None:
        (args.report_dir / "prerequisite_gate.json").write_text(
            json.dumps(gate, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    if gate["verdict"] != "GO":
        print(
            json.dumps(
                {"valid": False, "error": "WEEK9_GATE is not GO", "gate": gate},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    with SessionLocal() as session:
        summary = run_decision_engine(session, args.scenario_code, dry_run=args.dry_run)
        payload = summary.__dict__
        if not args.dry_run:
            report = write_decision_reports(session, summary.run_code, report_dir=args.report_dir)
            payload["report"] = report
    if args.report_dir is not None:
        (args.report_dir / "execution_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
