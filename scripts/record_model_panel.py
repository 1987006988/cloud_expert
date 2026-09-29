from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select

from cloud_expert.database.models.review import ModelReviewRun
from cloud_expert.database.session import SessionLocal
from cloud_expert.review.consensus import MODEL, fingerprint

POLICY_VERSION = "dual_model_class_audit_v1"


def _load(path: Path, stage: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError(f"invalid {stage} report")
    if payload.get("stage") != stage:
        raise ValueError(f"wrong stage for {stage} report")
    if payload.get("customer_eligibility_granted") is not False:
        raise ValueError("class audit cannot grant customer eligibility")
    if payload.get("per_object_semantic_review_complete") is not False:
        raise ValueError("class audit cannot claim full per-object review")
    return payload


def record_panel(report_dir: Path, *, apply: bool = False) -> dict[str, Any]:
    primary = _load(report_dir / "primary.json", "primary_class_audit")
    adversarial = _load(report_dir / "adversarial.json", "adversarial_class_audit")
    arbitration = _load(report_dir / "arbitration.json", "class_arbitration")
    if primary.get("model") != MODEL or adversarial.get("model") != MODEL:
        raise ValueError("both reviews must identify the approved highest-tier model")
    if primary.get("agent_id") == adversarial.get("agent_id"):
        raise ValueError("primary and adversarial review must be independent")
    if arbitration.get("primary_agent_id") != primary.get("agent_id") or arbitration.get(
        "adversarial_agent_id"
    ) != adversarial.get("agent_id"):
        raise ValueError("arbitration must reference both actual review sessions")
    if len({row.get("precheck_run_code") for row in (primary, adversarial, arbitration)}) != 1:
        raise ValueError("reports do not share the same precheck")
    precheck_code = primary["precheck_run_code"]
    with SessionLocal() as session:
        precheck = session.scalar(
            select(ModelReviewRun).where(ModelReviewRun.run_code == precheck_code)
        )
        if precheck is None or precheck.reviewer_model != "deterministic_evidence_precheck":
            raise ValueError("referenced deterministic precheck is not present")
        payloads = (primary, adversarial, arbitration)
        run_codes = [f"{row['stage']}_{fingerprint(row)[:16]}" for row in payloads]
        summary: dict[str, Any] = {
            "precheck_run_code": precheck_code,
            "run_codes": run_codes,
            "customer_eligibility_granted": False,
            "per_object_semantic_review_complete": False,
            "applied": apply,
        }
        if not apply:
            return summary
        for row, run_code in zip(payloads, run_codes, strict=True):
            if session.scalar(select(ModelReviewRun).where(ModelReviewRun.run_code == run_code)):
                continue
            session.add(
                ModelReviewRun(
                    run_code=run_code,
                    policy_version=POLICY_VERSION,
                    reviewer_model=(
                        MODEL if row["stage"] != "class_arbitration" else "dual_model_arbitration"
                    ),
                    input_fingerprint=fingerprint(row),
                    reviewed_at=datetime.now(UTC),
                    summary_json={
                        "stage": row["stage"],
                        "precheck_run_code": precheck_code,
                        "report_sha256": fingerprint(row),
                        "agent_id": row.get("agent_id"),
                        "primary_run_code": run_codes[0],
                        "adversarial_run_code": run_codes[1],
                        "customer_eligibility_granted": False,
                        "per_object_semantic_review_complete": False,
                    },
                )
            )
        session.commit()
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = record_panel(args.report_dir, apply=args.apply)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
