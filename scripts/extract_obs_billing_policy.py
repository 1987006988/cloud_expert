from __future__ import annotations

import argparse
import json

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.obs_billing import persist_billing_clauses


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract official OBS billing clauses, not prices")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        result = persist_billing_clauses(session)
        if args.apply:
            session.commit()
        else:
            session.rollback()
        result["applied"] = args.apply
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
