from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from check_week09_gate import check_week09_gate
from sqlalchemy import func, select

from cloud_expert.database.models.decision import (
    CandidateDecisionResult,
    DecisionRun,
    DecisionScenario,
    ScoringPolicy,
)
from cloud_expert.database.session import SessionLocal
from cloud_expert.decision.validation import validate_policy_directory, validate_scenario_directory

REPORT_DIR = Path("reports") / "week10_gate"
REQUIRED_DOCS = [
    "docs/MAPPING_ARCHITECTURE.md",
    "docs/COMPUTE_MAPPING_POLICY.md",
    "docs/OBJECT_STORAGE_MAPPING_POLICY.md",
    "docs/EVIDENCE_PACKAGE_ARCHITECTURE.md",
    "docs/CUSTOMER_OUTPUT_ELIGIBILITY.md",
    "docs/PRICING_ARCHITECTURE.md",
    "docs/PRICE_SKU_MODEL.md",
    "docs/TCO_CALCULATION_POLICY.md",
    "docs/CURRENCY_AND_TAX_POLICY.md",
]


def _artifact_status() -> dict[str, Any]:
    policy_validation = validate_policy_directory()
    scenario_validation = validate_scenario_directory()
    with SessionLocal() as session:
        scenarios = session.scalar(select(func.count()).select_from(DecisionScenario)) or 0
        policies = session.scalar(select(func.count()).select_from(ScoringPolicy)) or 0
        runs = session.scalar(select(func.count()).select_from(DecisionRun)) or 0
        results = session.scalar(select(func.count()).select_from(CandidateDecisionResult)) or 0
    missing_docs = [doc for doc in REQUIRED_DOCS if not Path(doc).exists()]
    errors: list[str] = []
    if not policy_validation["valid"]:
        errors.append("scoring policy validation failed")
    if not scenario_validation["valid"]:
        errors.append("decision scenario validation failed")
    if scenarios == 0:
        errors.append("no DecisionScenario rows are present")
    if policies == 0:
        errors.append("no ScoringPolicy rows are present")
    if runs == 0:
        errors.append("no DecisionRun rows are present")
    if results == 0:
        errors.append("no CandidateDecisionResult rows are present")
    return {
        "policy_validation": policy_validation,
        "scenario_validation": scenario_validation,
        "decision_scenarios": scenarios,
        "scoring_policies": policies,
        "decision_runs": runs,
        "candidate_decision_results": results,
        "missing_required_docs": missing_docs,
        "errors": errors,
        "valid": not errors,
    }


def check_week10_gate() -> dict[str, Any]:
    week9 = check_week09_gate()
    artifacts = _artifact_status()
    blockers: list[str] = []
    if week9["verdict"] != "GO":
        blockers.append("W10-B001-week9-gate")
    if not artifacts["policy_validation"]["valid"]:
        blockers.append("W10-B002-scoring-policy")
    if not artifacts["scenario_validation"]["valid"]:
        blockers.append("W10-B003-decision-scenario")
    if not artifacts["valid"]:
        blockers.append("W10-B004-decision-artifacts")
    return {
        "gate": "WEEK10_GATE",
        "verdict": "GO" if not blockers else "NO-GO",
        "week9_gate": week9,
        "artifacts": artifacts,
        "blocking_items": blockers,
        "notes": [
            "Decision results are internal-only machine-generated candidates until reviewed.",
            "Blocked or incomplete-cost candidates are not eligible for formal ranking.",
        ],
    }


def write_gate_reports(result: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "validation_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (REPORT_DIR / "gate_summary.md").write_text(
        "\n".join(
            [
                "# Week 10 Gate Summary",
                "",
                f"- Verdict: `{result['verdict']}`",
                f"- Week9 Gate: `{result['week9_gate']['verdict']}`",
                f"- Blocking items: {len(result['blocking_items'])}",
                f"- Decision runs: {result['artifacts']['decision_runs']}",
                f"- Candidate results: {result['artifacts']['candidate_decision_results']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (REPORT_DIR / "unresolved_blockers.md").write_text(
        "# Unresolved Blockers\n\n"
        + ("\n".join(f"- `{item}`" for item in result["blocking_items"]) or "None\n"),
        encoding="utf-8",
    )
    (REPORT_DIR / "dependency_status.md").write_text(
        "# Dependency Status\n\n"
        + json.dumps(result["artifacts"], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (REPORT_DIR / "recommended_next_actions.md").write_text(
        "# Recommended Next Actions\n\n"
        + (
            "- Close listed blockers before Week 11.\n"
            if result["blocking_items"]
            else "- Proceed to independent review before customer-facing work.\n"
        ),
        encoding="utf-8",
    )


def main() -> int:
    result = check_week10_gate()
    write_gate_reports(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
