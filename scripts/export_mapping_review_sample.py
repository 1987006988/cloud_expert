from __future__ import annotations

import argparse

from _bootstrap import ROOT

from cloud_expert.mapping.pipeline import make_session
from cloud_expert.mapping.reports import export_review_sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports/review_samples/week07_mapping_review.csv")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    with make_session() as session:
        count = export_review_sample(session, ROOT / args.output, args.limit)
    print(f"exported_review_rows={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
