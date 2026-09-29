import argparse
import json
from pathlib import Path

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.pricing.aliyun_promotion import extract_catalog_record
from cloud_expert.pricing.extraction import persist_price_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Import bounded internal catalog estimates")
    parser.add_argument("--catalog-evidence", type=int, action="append", required=True)
    parser.add_argument("--tax-evidence", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("report already exists; select a new run path")
    with SessionLocal() as session:
        records = [
            extract_catalog_record(session, eid, args.tax_evidence) for eid in args.catalog_evidence
        ]
        output = {
            "applied": args.apply,
            "customer_approved": False,
            "realtime": False,
            "records": [json.loads(row.evidence_excerpt) for row in records],
        }
        if args.apply:
            output["persistence"] = persist_price_records(session, records)
    atomic_write_text(args.report, json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
