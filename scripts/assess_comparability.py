import argparse
import json

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.normalization.canonical_service import assess_comparability


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess field-level comparability readiness.")
    parser.add_argument("--run-key", default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        summary = assess_comparability(session, run_key=args.run_key)
        session.commit()
    print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
