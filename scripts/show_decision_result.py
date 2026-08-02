from __future__ import annotations

import argparse
import json

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.decision.pipeline import result_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-code", required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    with SessionLocal() as session:
        rows = result_rows(session, args.run_code)[: args.limit]
    print(
        json.dumps(
            {"run_code": args.run_code, "results": rows}, ensure_ascii=False, indent=2, default=str
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
