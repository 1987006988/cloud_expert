import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.normalization.reports import (
    build_cross_provider_coverage_report,
    write_coverage_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate cross-provider canonical coverage.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/normalization"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        report = build_cross_provider_coverage_report(session)
    json_path = args.output_dir / "cross_provider_coverage.json"
    md_path = args.output_dir / "cross_provider_coverage.md"
    atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2, default=str))
    write_coverage_markdown(report, md_path)
    print(json.dumps({"outputs": [str(json_path), str(md_path)]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
