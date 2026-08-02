from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.decision import DecisionRun
from cloud_expert.database.session import SessionLocal
from cloud_expert.decision.pipeline import _upsert_sensitivity
from cloud_expert.decision.reporting import write_decision_reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-code", required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.scalar(select(DecisionRun).where(DecisionRun.run_code == args.run_code))
        if run is None:
            print(json.dumps({"valid": False, "error": "DecisionRun not found"}, indent=2))
            return 1
        _upsert_sensitivity(session, run)
        session.commit()
        payload = write_decision_reports(session, args.run_code)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
