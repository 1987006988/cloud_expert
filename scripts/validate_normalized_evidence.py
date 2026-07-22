import json

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.session import SessionLocal


def main() -> int:
    with SessionLocal() as session:
        total = int(session.scalar(select(func.count()).select_from(NormalizedSpecification)) or 0)
        missing = int(
            session.scalar(
                select(func.count())
                .select_from(NormalizedSpecification)
                .outerjoin(Evidence, NormalizedSpecification.evidence_id == Evidence.id)
                .where(Evidence.id.is_(None))
            )
            or 0
        )
    result = {"normalized_specifications": total, "missing_evidence_links": missing}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
