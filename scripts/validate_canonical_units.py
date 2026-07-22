import json

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.canonical import CanonicalFieldDefinition, NormalizedSpecification
from cloud_expert.database.session import SessionLocal


def main() -> int:
    errors: list[dict[str, object]] = []
    with SessionLocal() as session:
        rows = session.execute(
            select(NormalizedSpecification, CanonicalFieldDefinition).join(
                CanonicalFieldDefinition,
                NormalizedSpecification.canonical_field_id == CanonicalFieldDefinition.id,
            )
        ).all()
        for spec, field in rows:
            if field.canonical_unit is not None and spec.canonical_unit != field.canonical_unit:
                errors.append(
                    {
                        "normalized_specification_id": spec.id,
                        "canonical_field_code": field.code,
                        "expected_unit": field.canonical_unit,
                        "actual_unit": spec.canonical_unit,
                    }
                )
    print(json.dumps({"checked": len(rows), "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
