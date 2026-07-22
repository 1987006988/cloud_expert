import argparse
import json

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import SpecificationScopeType
from cloud_expert.database.models.canonical import CanonicalFieldDefinition, NormalizedSpecification
from cloud_expert.database.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate normalized specification scopes.")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    allowed = set(SpecificationScopeType.values())
    mismatches: list[dict[str, object]] = []
    with SessionLocal() as session:
        scope_counts = {
            str(scope): int(count)
            for scope, count in session.execute(
                select(NormalizedSpecification.scope_type, func.count()).group_by(
                    NormalizedSpecification.scope_type
                )
            ).all()
        }
        rows = session.execute(
            select(NormalizedSpecification, CanonicalFieldDefinition).join(
                CanonicalFieldDefinition,
                NormalizedSpecification.canonical_field_id == CanonicalFieldDefinition.id,
            )
        ).all()
        for spec, field in rows:
            if spec.scope_type != field.default_scope_type:
                mismatches.append(
                    {
                        "normalized_specification_id": spec.id,
                        "canonical_field_code": field.code,
                        "expected_scope_type": field.default_scope_type,
                        "actual_scope_type": spec.scope_type,
                    }
                )
    unknown = sorted(set(scope_counts) - allowed)
    result = {
        "scope_counts": scope_counts,
        "unknown_scopes": unknown,
        "scope_mismatch_warning_count": len(mismatches),
        "scope_mismatch_warnings": mismatches,
    }
    if args.summary_only:
        result["scope_mismatch_warnings"] = []
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
