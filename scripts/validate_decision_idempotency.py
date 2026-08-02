from __future__ import annotations

import json

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.models.decision import DecisionRun, DecisionScenario
from cloud_expert.database.session import SessionLocal
from cloud_expert.decision.pipeline import run_decision_engine


def validate_decision_idempotency() -> dict[str, object]:
    with SessionLocal() as session:
        scenario = session.scalar(select(DecisionScenario).order_by(DecisionScenario.id))
        if scenario is None:
            return {"valid": False, "errors": ["no DecisionScenario rows are present"]}
        before = session.scalar(select(func.count()).select_from(DecisionRun)) or 0
        first = run_decision_engine(session, scenario.scenario_code)
        middle = session.scalar(select(func.count()).select_from(DecisionRun)) or 0
        second = run_decision_engine(session, scenario.scenario_code)
        after = session.scalar(select(func.count()).select_from(DecisionRun)) or 0
    errors: list[str] = []
    if first.run_code != second.run_code:
        errors.append("repeat run produced a different run_code")
    if after != middle:
        errors.append("repeat run created duplicate DecisionRun rows")
    return {
        "scenario_code": scenario.scenario_code,
        "run_code": first.run_code,
        "runs_before": before,
        "runs_after_first": middle,
        "runs_after_second": after,
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    result = validate_decision_idempotency()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
