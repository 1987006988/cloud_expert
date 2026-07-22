import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.quality.reports import build_quality_report, write_quality_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a product data quality report.")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        report = build_quality_report(
            session,
            provider_code=args.provider,
            product_code=args.product,
        )
    output = args.output or Path("data/reports") / f"{args.provider}_{args.product}_quality.json"
    write_quality_report(report, output)
    print(
        json.dumps(
            {"output": str(output), "report": report}, ensure_ascii=False, indent=2, default=str
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
