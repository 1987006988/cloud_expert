from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import DecisionOutputLevel, DecisionReviewStatus
from cloud_expert.database.models.decision import (
    CandidateDecisionResult,
    DecisionRun,
    DecisionScenario,
    DecisionSensitivityResult,
    DimensionScore,
    ScenarioRequirement,
)
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.decision.pipeline import result_rows, write_review_sample

REPORT_DIR = Path("reports") / "decision"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def latest_run(session: Session) -> DecisionRun | None:
    return session.scalar(
        select(DecisionRun).order_by(DecisionRun.generated_at.desc(), DecisionRun.id.desc())
    )


def decision_report_payload(session: Session, run_code: str | None = None) -> dict[str, Any]:
    run = (
        session.scalar(select(DecisionRun).where(DecisionRun.run_code == run_code))
        if run_code
        else latest_run(session)
    )
    if run is None:
        return {
            "decision_runs": 0,
            "candidate_results": 0,
            "valid": False,
            "errors": ["no DecisionRun rows are present"],
        }
    results = list(
        session.execute(
            select(CandidateDecisionResult).where(CandidateDecisionResult.decision_run_id == run.id)
        ).scalars()
    )
    status_counts = Counter(result.decision_status for result in results)
    confidence_counts = Counter(result.confidence_level for result in results)
    output_counts = Counter(result.output_level for result in results)
    review_counts = Counter(result.review_status for result in results)
    dimension_counts = Counter(
        row[0]
        for row in session.execute(
            select(DimensionScore.status)
            .join(CandidateDecisionResult)
            .where(CandidateDecisionResult.decision_run_id == run.id)
        ).all()
    )
    sensitivity = session.scalar(
        select(DecisionSensitivityResult).where(DecisionSensitivityResult.decision_run_id == run.id)
    )
    return {
        "decision_runs": session.scalar(select(func.count()).select_from(DecisionRun)) or 0,
        "run_code": run.run_code,
        "scenario_code": run.scenario.scenario_code,
        "scenario_version": run.scenario_version,
        "policy_version": run.policy_version,
        "candidate_results": len(results),
        "status_counts": dict(status_counts),
        "confidence_counts": dict(confidence_counts),
        "output_counts": dict(output_counts),
        "review_counts": dict(review_counts),
        "dimension_status_counts": dict(dimension_counts),
        "eligible": run.eligible_count,
        "blocked": run.blocked_count,
        "requires_review": run.review_count,
        "warnings": run.warning_count,
        "customer_eligible": output_counts.get(
            DecisionOutputLevel.CUSTOMER_ELIGIBLE_CANDIDATE.value, 0
        ),
        "internal_only": output_counts.get(DecisionOutputLevel.INTERNAL_ONLY.value, 0),
        "machine_generated": review_counts.get(DecisionReviewStatus.MACHINE_GENERATED.value, 0),
        "sensitivity_status": sensitivity.sensitivity_status if sensitivity else "missing",
        "valid": True,
        "errors": [],
    }


def write_decision_reports(
    session: Session, run_code: str | None = None, *, report_dir: Path | None = None
) -> dict[str, Any]:
    destination = report_dir or REPORT_DIR
    payload = decision_report_payload(session, run_code)
    destination.mkdir(parents=True, exist_ok=True)
    _write_json(destination / "decision_results.json", payload)
    if not payload["valid"]:
        _write(
            destination / "decision_run_summary.md", "# Decision Run Summary\n\nNo run exists.\n"
        )
        return payload
    run = session.scalar(select(DecisionRun).where(DecisionRun.run_code == payload["run_code"]))
    assert run is not None
    _write(
        destination / "decision_run_summary.md",
        "\n".join(
            [
                "# Decision Run Summary",
                "",
                f"- Run: `{run.run_code}`",
                f"- Scenario: `{payload['scenario_code']}` `{payload['scenario_version']}`",
                f"- Policy version: `{payload['policy_version']}`",
                f"- Candidates: {payload['candidate_results']}",
                f"- Eligible or conditional: {payload['eligible']}",
                f"- Blocked or invalid: {payload['blocked']}",
                f"- Requires review: {payload['requires_review']}",
                "- Output level: internal-only by default",
                "",
            ]
        ),
    )
    _write(
        destination / "scenario_coverage.md",
        f"# Scenario Coverage\n\nScenarios: {session.scalar(select(func.count()).select_from(DecisionScenario)) or 0}\n"
        f"\nRequirements: {session.scalar(select(func.count()).select_from(ScenarioRequirement)) or 0}\n",
    )
    _write(
        destination / "hard_block_summary.md",
        f"# Hard Block Summary\n\nBlocked or invalid results: {payload['blocked']}\n",
    )
    _write(
        destination / "dimension_score_distribution.md",
        "# Dimension Score Distribution\n\n"
        + json.dumps(payload["dimension_status_counts"], ensure_ascii=False, indent=2),
    )
    _write(
        destination / "confidence_summary.md",
        "# Confidence Summary\n\n"
        + json.dumps(payload["confidence_counts"], ensure_ascii=False, indent=2),
    )
    _write(
        destination / "completeness_summary.md",
        "# Completeness Summary\n\nCompleteness is stored separately from Business Fit and Confidence.\n",
    )
    _write(
        destination / "missing_data_summary.md",
        "# Missing Data Summary\n\nMissing dimensions are marked as insufficient evidence or excluded; they are not scored as zero.\n",
    )
    _write(
        destination / "evidence_quality.md",
        f"# Evidence Quality\n\nEvidence packages: {session.scalar(select(func.count()).select_from(EvidencePackage)) or 0}\n"
        f"\nCustomer-eligible decision candidates: {payload['customer_eligible']}\n",
    )
    _write(
        destination / "cost_input_quality.md",
        f"# Cost Input Quality\n\nPriceSKU: {session.scalar(select(func.count()).select_from(PriceSKU)) or 0}\n"
        f"\nPriceSnapshot: {session.scalar(select(func.count()).select_from(PriceSnapshot)) or 0}\n"
        f"\nTCOResult: {session.scalar(select(func.count()).select_from(TCOResult)) or 0}\n",
    )
    _write(
        destination / "sensitivity_summary.md",
        f"# Sensitivity Summary\n\nStatus: `{payload['sensitivity_status']}`\n",
    )
    _write(
        destination / "review_status.md",
        "# Review Status\n\n" + json.dumps(payload["review_counts"], ensure_ascii=False, indent=2),
    )
    _write(
        destination / "customer_eligibility.md",
        f"# Customer Eligibility\n\nInternal-only: {payload['internal_only']}\n\nCustomer eligible: {payload['customer_eligible']}\n",
    )
    rows = result_rows(session, payload["run_code"])
    _write_json(destination / "decision_result_rows.json", rows)
    if report_dir is not None:
        write_review_sample(session, payload["run_code"], destination / "review_sample.csv")
    else:
        write_review_sample(session, payload["run_code"])
    return payload


def export_markdown_report(session: Session, run_code: str, path: Path) -> None:
    payload = decision_report_payload(session, run_code)
    rows = result_rows(session, run_code)[:20]
    lines = [
        "# Internal Decision Candidate Report",
        "",
        "Audience: internal",
        "",
        f"Run: `{payload.get('run_code', run_code)}`",
        f"Scenario: `{payload.get('scenario_code', '')}`",
        "",
        "This report is not customer-facing sales material.",
        "",
        "## Summary",
        "",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "",
        "## Sample Results",
        "",
    ]
    for row in rows:
        lines.append(
            f"- Result {row['decision_result_id']}: {row['provider']} "
            f"{row['decision_status']} confidence={row['confidence_score']}"
        )
    _write(path, "\n".join(lines) + "\n")
