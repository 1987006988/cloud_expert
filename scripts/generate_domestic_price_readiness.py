from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.domestic_readiness import generate_domestic_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate evidence-bounded domestic cost details")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=False)
    with SessionLocal() as session:
        report = generate_domestic_readiness(session)
        report["applied"] = args.apply
        if args.apply:
            session.commit()
        else:
            session.rollback()
    serialized = json.dumps(report, indent=2)
    (args.report_dir / "cost_details.json").write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
