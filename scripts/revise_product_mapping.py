from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.mapping.revision import prepare_product_mapping_refresh, revise_product_mapping


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Version a product mapping using repaired official definitions."
    )
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prepare-approved-refresh", action="store_true")
    parser.add_argument("--expected-subject-sha256")
    args = parser.parse_args()
    if args.prepare_approved_refresh != bool(args.expected_subject_sha256):
        parser.error("Approved refresh requires both the refresh flag and expected subject SHA256")
    with SessionLocal() as session:
        result = (
            prepare_product_mapping_refresh(
                session, args.candidate_id, expected_subject_sha256=args.expected_subject_sha256
            )
            if args.prepare_approved_refresh
            else revise_product_mapping(session, args.candidate_id)
        )
        if args.apply:
            session.commit()
        else:
            session.rollback()
    result["applied"] = args.apply
    if args.apply:
        suffix = f"_refresh_{result['new_id']}" if args.prepare_approved_refresh else ""
        path = (
            Path("reports/remediation/mapping_revisions")
            / f"candidate_{args.candidate_id}{suffix}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
