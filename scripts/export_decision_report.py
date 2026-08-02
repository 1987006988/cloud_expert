from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.decision.reporting import export_markdown_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-code", required=True)
    parser.add_argument("--format", choices=["markdown"], default="markdown")
    parser.add_argument("--audience", choices=["internal"], default="internal")
    parser.add_argument("--output", default="reports/decision/internal_decision_report.md")
    args = parser.parse_args()
    with SessionLocal() as session:
        export_markdown_report(session, args.run_code, Path(args.output))
    print(json.dumps({"valid": True, "output": args.output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
