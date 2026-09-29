from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml

from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.workflow import apply_mapping_pilot_result

ROOT = Path(__file__).resolve().parents[1]
PILOT_ROOT = (ROOT / "reports/model_review/week14_pilot").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply a verified, scope-limited model-review result."
    )
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    if not report_dir.is_relative_to(PILOT_ROOT):
        raise SystemExit("report directory must be under the Week14 pilot root")
    authorization = yaml.safe_load(
        (ROOT / "config/model_review/review_authorization.yaml").read_text(encoding="utf-8")
    )
    if authorization.get("external_data_transfer_approved") is not True:
        raise SystemExit("external review authorization is not active")
    with SessionLocal() as session:
        result = apply_mapping_pilot_result(
            session, report_dir, approved_model=authorization["approved_model"]
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
