from __future__ import annotations

import argparse
from datetime import UTC, datetime

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.enums import ReviewStatus
from cloud_expert.database.models.mapping import MappingReview
from cloud_expert.mapping.pipeline import make_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--review-status", choices=ReviewStatus.values(), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    with make_session() as session:
        session.add(
            MappingReview(
                mapping_candidate_id=args.candidate_id,
                review_status=args.review_status,
                reviewer=args.reviewer,
                reviewed_at=datetime.now(UTC),
                review_notes=args.notes,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    print("review_recorded=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
