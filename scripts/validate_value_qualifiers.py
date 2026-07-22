import json

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import ValueQualifier
from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.session import SessionLocal


def main() -> int:
    allowed = set(ValueQualifier.values())
    with SessionLocal() as session:
        counts = {
            str(qualifier): int(count)
            for qualifier, count in session.execute(
                select(NormalizedSpecification.value_qualifier, func.count()).group_by(
                    NormalizedSpecification.value_qualifier
                )
            ).all()
        }
    unknown = sorted(set(counts) - allowed)
    result = {"qualifier_counts": counts, "unknown_qualifiers": unknown}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
