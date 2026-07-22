import argparse
import json

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.normalization.canonical_service import (
    assess_comparability,
    normalize_specifications,
    seed_canonical_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize parsed product specifications.")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--product", default=None)
    parser.add_argument("--source-database-label", default=None)
    parser.add_argument("--run-key", default=None)
    parser.add_argument("--skip-comparability", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        seed_summary = seed_canonical_registry(session)
        normalization_summary = normalize_specifications(
            session,
            provider_code=args.provider,
            product_code=args.product,
            source_database_label=args.source_database_label,
            run_key=args.run_key,
        )
        comparability_summary = None
        if not args.skip_comparability:
            comparability_summary = assess_comparability(
                session, run_key=normalization_summary.run_key
            )
        session.commit()
    result = {
        "seed": seed_summary.__dict__,
        "normalization": normalization_summary.__dict__,
        "comparability": None if comparability_summary is None else comparability_summary.__dict__,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
