from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import DecisionOutputLevel
from cloud_expert.database.models.decision import (
    CandidateDecisionResult,
    DecisionRun,
    DimensionScore,
)
from cloud_expert.database.session import SessionLocal


def validate_decision_evidence(run_code: str | None = None) -> dict[str, object]:
    with SessionLocal() as session:
        run_filter = []
        if run_code:
            run = session.scalar(select(DecisionRun).where(DecisionRun.run_code == run_code))
            if run is None:
                return {"valid": False, "errors": [f"DecisionRun not found: {run_code}"]}
            run_filter.append(CandidateDecisionResult.decision_run_id == run.id)
        result_count = (
            session.scalar(
                select(func.count()).select_from(CandidateDecisionResult).where(*run_filter)
            )
            or 0
        )
        linked_scores = (
            session.scalar(
                select(func.count())
                .select_from(DimensionScore)
                .join(CandidateDecisionResult)
                .where(*run_filter, DimensionScore.evidence_package_id.is_not(None))
            )
            or 0
        )
        customer_eligible = (
            session.scalar(
                select(func.count())
                .select_from(CandidateDecisionResult)
                .where(
                    *run_filter,
                    CandidateDecisionResult.output_level
                    == DecisionOutputLevel.CUSTOMER_ELIGIBLE_CANDIDATE.value,
                )
            )
            or 0
        )
    errors: list[str] = []
    if result_count == 0:
        errors.append("no CandidateDecisionResult rows are present")
    if linked_scores == 0:
        errors.append("no DimensionScore rows link to EvidencePackage")
    if customer_eligible:
        errors.append("machine-generated results must not be customer eligible")
    return {
        "candidate_results": result_count,
        "dimension_scores_with_evidence_package": linked_scores,
        "customer_eligible_candidates": customer_eligible,
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-code")
    args = parser.parse_args()
    result = validate_decision_evidence(args.run_code)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
