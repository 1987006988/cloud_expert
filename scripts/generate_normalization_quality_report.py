import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.normalization.reports import build_normalization_quality_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate normalization quality report.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/normalization/normalization_quality_report.json"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        report = build_normalization_quality_report(session)
    atomic_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({"output": str(args.output), "report": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
