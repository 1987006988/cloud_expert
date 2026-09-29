from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT as _ROOT  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.registry.loader import load_registry_entries
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text
from cloud_expert.pricing.aliyun_capture import SOURCE_ID, import_catalog, inspect_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled import of Aliyun browser catalog")
    parser.add_argument("capture", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("report already exists; select a new run path")
    entry = next(e for e in load_registry_entries() if e.source_id == SOURCE_ID)
    captured, records = inspect_catalog(args.capture.read_bytes())
    result = {"mode": "dry_run", "captured_at": captured.isoformat(), "rows": len(records)}
    if args.apply:
        with SessionLocal() as session:
            result = {"mode": "apply", **import_catalog(session, entry, args.capture)}
    atomic_write_text(args.report, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
