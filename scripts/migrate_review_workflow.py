from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.migration import migrate_precheck

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an additive model-review queue overlay.")
    parser.add_argument("--from", dest="source", choices=["human"], required=True)
    parser.add_argument("--to", dest="target", choices=["model"], required=True)
    parser.add_argument("--precheck-run-code", default="model_review_7a317e83b89979fd")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        result = migrate_precheck(session, args.precheck_run_code, apply=args.apply)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    fingerprint = sha256(payload.encode("utf-8")).hexdigest()[:12]
    report_dir = ROOT / "reports/model_review/migrations" / f"run_{fingerprint}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "migration_summary.json").write_text(payload, encoding="utf-8")
    result["report_dir"] = str(report_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["missing_targets"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
