from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.enums import DecisionReviewStatus
from cloud_expert.database.models.decision import CandidateDecisionResult, DecisionReview
from cloud_expert.database.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-id", type=int, required=True)
    parser.add_argument(
        "--decision",
        choices=[
            DecisionReviewStatus.INTERNALLY_APPROVED.value,
            DecisionReviewStatus.REJECTED.value,
            DecisionReviewStatus.CORRECTED.value,
        ],
        required=True,
    )
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", required=True)
    args = parser.parse_args()
    if not args.reviewer.strip():
        print(json.dumps({"valid": False, "error": "reviewer cannot be empty"}, indent=2))
        return 1
    with SessionLocal() as session:
        result = session.scalar(
            select(CandidateDecisionResult).where(CandidateDecisionResult.id == args.result_id)
        )
        if result is None:
            print(
                json.dumps({"valid": False, "error": "CandidateDecisionResult not found"}, indent=2)
            )
            return 1
        review = DecisionReview(
            candidate_result_id=result.id,
            reviewer=args.reviewer,
            reviewed_at=datetime.now(UTC),
            decision=args.decision,
            notes=args.notes,
        )
        session.add(review)
        result.review_status = args.decision
        session.commit()
        payload = {"valid": True, "review_id": review.id, "result_id": result.id}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
