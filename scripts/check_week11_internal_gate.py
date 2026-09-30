"""Separate internal bounded-cost development gate; never replaces customer Gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from check_week09_gate import check_week09_gate
from check_week10_gate import check_week10_gate

from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.internal_gate import internal_cost_readiness


def check_week11_internal_gate(candidate_id: int) -> dict[str, Any]:
    week9 = check_week09_gate()
    week10 = check_week10_gate()
    blockers: list[str] = []
    if week9["verdict"] != "GO":
        blockers.append("W11I-B001-week9-gate")
    if week10["verdict"] != "GO":
        blockers.append("W11I-B002-week10-gate")
    with SessionLocal() as session:
        readiness = internal_cost_readiness(session, candidate_id)
    blockers.extend(readiness["blocking_items"])
    return {
        "gate": "WEEK11_INTERNAL_BOUNDED_COST_GATE",
        "verdict": "NO-GO" if blockers else "GO",
        "candidate_id": candidate_id,
        "week9_gate": week9,
        "week10_gate": week10,
        "readiness": readiness,
        "blocking_items": blockers,
        "internal_development_authorized": not blockers,
        "allowed_operations": readiness["allowed_operations"] if not blockers else [],
        "customer_output_allowed": False,
        "whole_week11_complete": False,
        "subsequent_whole_week_gates_passed": False,
        "note": "Exact reviewed bounded-cost scope only; not competitive ranking or sales completion.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", type=int, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=False)
    result = check_week11_internal_gate(args.candidate_id)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    (args.report_dir / "validation_results.json").write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
