import argparse
import json
from pathlib import Path

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.pricing.supporting_policies import persist_policy_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract verified pricing policy evidence")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("report exists; select a new run path")
    with SessionLocal() as session:
        result = persist_policy_evidence(session)
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(args.report, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
