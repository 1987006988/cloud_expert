import argparse
import json

import _bootstrap  # noqa: F401
from sqlalchemy import delete, func, select

from cloud_expert.database.models.canonical import (
    ComparabilityAssessment,
    NormalizationRun,
    NormalizedSpecification,
)
from cloud_expert.database.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete derived canonical normalization rows.")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--confirm-derived-delete", action="store_true")
    args = parser.parse_args()
    if not args.confirm_derived_delete:
        print(
            json.dumps({"error": "pass --confirm-derived-delete to delete derived rows"}, indent=2)
        )
        return 2

    with SessionLocal() as session:
        run = session.scalar(
            select(NormalizationRun).where(NormalizationRun.run_key == args.run_key)
        )
        if run is None:
            print(json.dumps({"deleted": 0, "message": "run_key not found"}, indent=2))
            return 0
        comparability_count = int(
            session.scalar(
                select(func.count())
                .select_from(ComparabilityAssessment)
                .where(ComparabilityAssessment.normalization_run_id == run.id)
            )
            or 0
        )
        normalized_count = int(
            session.scalar(
                select(func.count())
                .select_from(NormalizedSpecification)
                .where(NormalizedSpecification.normalization_run_id == run.id)
            )
            or 0
        )
        session.execute(
            delete(ComparabilityAssessment).where(
                ComparabilityAssessment.normalization_run_id == run.id
            )
        )
        session.execute(
            delete(NormalizedSpecification).where(
                NormalizedSpecification.normalization_run_id == run.id
            )
        )
        session.delete(run)
        session.commit()
    result = {
        "deleted_comparability_assessments": comparability_count,
        "deleted_normalized_specifications": normalized_count,
        "deleted_normalization_run": args.run_key,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
