from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing.api_capture import import_api_capture
from cloud_expert.pricing.huawei_api import PricingQuery


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import owner-authorized API Explorer response copy"
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--captured-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--query-envelope", type=Path)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    entry = get_entry_by_source_id(args.source_id)
    if entry is None:
        parser.error("source is not registered")
    query = None
    if args.query_envelope:
        query = PricingQuery.model_validate(
            json.loads(args.query_envelope.read_text(encoding="utf-8"))["request"]
        )
    with SessionLocal() as session:
        result = import_api_capture(session, entry, args.response, args.captured_at, query=query)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
