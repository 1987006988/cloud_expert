from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import DecisionOutputLevel, DecisionReviewStatus, DecisionStatus
from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionRun
from cloud_expert.database.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-code", required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        run = session.scalar(select(DecisionRun).where(DecisionRun.run_code == args.run_code))
        if run is None:
            print(json.dumps({"valid": False, "errors": ["DecisionRun not found"]}, indent=2))
            return 1
        customer_eligible = (
            session.scalar(
                select(func.count())
                .select_from(CandidateDecisionResult)
                .where(
                    CandidateDecisionResult.decision_run_id == run.id,
                    CandidateDecisionResult.output_level
                    == DecisionOutputLevel.CUSTOMER_ELIGIBLE_CANDIDATE.value,
                )
            )
            or 0
        )
        internal_only = (
            session.scalar(
                select(func.count())
                .select_from(CandidateDecisionResult)
                .where(
                    CandidateDecisionResult.decision_run_id == run.id,
                    CandidateDecisionResult.output_level == DecisionOutputLevel.INTERNAL_ONLY.value,
                )
            )
            or 0
        )
        unsafe = (
            session.scalar(
                select(func.count())
                .select_from(CandidateDecisionResult)
                .where(
                    CandidateDecisionResult.decision_run_id == run.id,
                    CandidateDecisionResult.review_status
                    == DecisionReviewStatus.MACHINE_GENERATED.value,
                    CandidateDecisionResult.decision_status == DecisionStatus.ELIGIBLE.value,
                    CandidateDecisionResult.customer_eligible.is_(True),
                )
            )
            or 0
        )
    payload = {
        "run_code": args.run_code,
        "internal_only": internal_only,
        "customer_eligible_candidates": customer_eligible,
        "machine_generated_customer_eligible": unsafe,
        "valid": unsafe == 0,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
