from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml

from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.pilot import run_mapping_pilot

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated, report-only model review pilot.")
    parser.add_argument("--precheck-run-code", required=True)
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--model-id")
    args = parser.parse_args()
    authorization = yaml.safe_load(
        (ROOT / "config/model_review/review_authorization.yaml").read_text(encoding="utf-8")
    )
    if authorization.get("external_data_transfer_approved") is not True:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_EXTERNAL_DATA_APPROVAL",
                    "reason": authorization.get("reason"),
                    "database_writeback": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    resolution = json.loads(
        (ROOT / "reports/model_review/model_resolution.json").read_text(encoding="utf-8")
    )
    model_id = args.model_id or resolution.get("model_id")
    if (
        resolution.get("status") != "AVAILABLE"
        or resolution.get("fallback_used")
        or model_id != resolution.get("model_id")
        or model_id != authorization.get("approved_model")
    ):
        print(json.dumps({"status": "BLOCKED_MODEL_POLICY", "database_writeback": False}))
        return 1
    with SessionLocal() as session:
        result = run_mapping_pilot(
            session,
            args.precheck_run_code,
            args.candidate_id,
            ROOT / "reports/model_review/week14_pilot",
            model_id,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
