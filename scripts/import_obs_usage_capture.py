from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.usage_type_capture import import_usage_capture, validate_capture


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a bounded official OBS billing definition")
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    envelope = json.loads(args.capture.read_text(encoding="utf-8"))
    validate_capture(envelope)
    if args.apply:
        with SessionLocal() as session:
            result = import_usage_capture(session, envelope)
    else:
        result = {"validation": "passed", "database_writeback": False}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
