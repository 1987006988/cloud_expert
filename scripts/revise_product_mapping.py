from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.mapping.revision import revise_product_mapping


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Version a product mapping using repaired official definitions."
    )
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        result = revise_product_mapping(session, args.candidate_id)
        if args.apply:
            session.commit()
        else:
            session.rollback()
    result["applied"] = args.apply
    if args.apply:
        path = Path("reports/remediation/mapping_revisions") / f"candidate_{args.candidate_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
