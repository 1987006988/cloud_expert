from __future__ import annotations

import json

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.enums import ReviewStatus
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.mapping.pipeline import make_session


def main() -> int:
    with make_session() as session:
        rows = session.scalars(
            select(MappingCandidate)
            .where(MappingCandidate.review_status == ReviewStatus.PENDING_REVIEW.value)
            .order_by(MappingCandidate.id)
            .limit(100)
        ).all()
        payload = [
            {
                "id": row.id,
                "mapping_level": row.mapping_level,
                "relationship_type": row.relationship_type,
                "candidate_status": row.candidate_status,
                "review_status": row.review_status,
            }
            for row in rows
        ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
