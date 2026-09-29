from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
import yaml
from check_week09_gate import check_week09_gate
from check_week10_gate import check_week10_gate
from check_week11_gate import check_week11_gate
from check_week12_gate import _junit_result, check_week12_gate
from check_week13_gate import check_week13_gate
from sqlalchemy import select
from validate_normalized_evidence import _validate_rows
from validate_price_evidence import validate_price_evidence

from cloud_expert.database.models.model_review_workflow import ModelReviewAssignment
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.session import SessionLocal
from cloud_expert.model_review.migration import review_queue_integrity
from cloud_expert.model_review.workflow import unresolved_review_count

ROOT = Path(__file__).resolve().parents[1]
RESOLUTION = ROOT / "reports/model_review/model_resolution.json"
AUTHORIZATION = ROOT / "config/model_review/review_authorization.yaml"
EVAL_RESULT = ROOT / "reports/evals/eval_results.json"
WEEK14_TEST_DIR = ROOT / "reports/week14_gate"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def check_week14_gate() -> dict[str, Any]:
    week9 = check_week09_gate()
    week10 = check_week10_gate()
    week11 = check_week11_gate()
    week12 = check_week12_gate()
    week13 = check_week13_gate()
    resolution = _read_json(RESOLUTION)
    authorization = yaml.safe_load(AUTHORIZATION.read_text(encoding="utf-8"))
    eval_result = _read_json(EVAL_RESULT)
    full_junit = _junit_result(WEEK14_TEST_DIR / "full_junit.xml")
    postgres_junit = _junit_result(WEEK14_TEST_DIR / "postgres_junit.xml")
    coverage_result = _read_json(WEEK14_TEST_DIR / "coverage.json")
    coverage_percent = (
        float(coverage_result["totals"]["percent_covered"])
        if coverage_result and isinstance(coverage_result.get("totals"), dict)
        else None
    )
    full_tests_verified = bool(
        full_junit
        and full_junit["tests"] >= 100
        and full_junit["failures"] == 0
        and full_junit["errors"] == 0
    )
    postgres_tests_verified = bool(
        postgres_junit
        and postgres_junit["tests"] >= 8
        and postgres_junit["failures"] == 0
        and postgres_junit["errors"] == 0
        and postgres_junit["skipped"] == 0
    )
    with SessionLocal() as session:
        evidence_issues = _validate_rows(session)
        queue_integrity = review_queue_integrity(session)
        assignments = list(
            session.scalars(select(ModelReviewAssignment).order_by(ModelReviewAssignment.id))
        )
        precheck = session.scalar(
            select(ModelReviewRun)
            .where(ModelReviewRun.reviewer_model == "deterministic_evidence_precheck")
            .order_by(ModelReviewRun.id.desc())
        )
        current_precheck_findings = (
            len(
                list(
                    session.scalars(
                        select(ModelReviewFinding.id).where(
                            ModelReviewFinding.run_id == precheck.id
                        )
                    )
                )
            )
            if precheck is not None
            else 0
        )
    evidence_breaks = sum(
        value
        for key, value in evidence_issues.items()
        if key != "samples" and isinstance(value, int)
    )
    state_counts = dict(Counter(row.review_state for row in assignments))
    model_probe_current = False
    if resolution and resolution.get("status") == "AVAILABLE":
        try:
            checked_at = datetime.fromisoformat(resolution["checked_at"])
            model_probe_current = datetime.now(UTC) - checked_at.astimezone(UTC) < timedelta(days=1)
        except (KeyError, TypeError, ValueError):
            pass
    price_evidence = validate_price_evidence()
    market_counts = week12["market_integrity"]["counts"]
    hard_stop: list[str] = []
    if week9["verdict"] != "GO" or week10["verdict"] != "GO":
        hard_stop.append("W14-H001-week9-or-week10-not-go")
    if evidence_breaks or not price_evidence["valid"]:
        hard_stop.append("W14-H002-evidence-chain-broken")
    if not week12["current_postgres_verified"] or not postgres_tests_verified:
        hard_stop.append("W14-H003-postgresql-not-verified")
    if not full_tests_verified:
        hard_stop.append("W14-H007-full-test-suite-not-running")
    if (
        market_counts["active_mapping_scope_errors"]
        or week12["market_integrity"]["customer_exposure_detected"]
    ):
        hard_stop.append("W14-H004-active-market-contamination")
    if market_counts["tco_product_market_mismatch"]:
        hard_stop.append("W14-H005-active-tco-market-error")
    if not week9["tco_validation"]["valid"]:
        hard_stop.append("W14-H006-tco-validation-error")
    mode = (
        "blocked_gate_only"
        if hard_stop
        else ("full_evaluation" if week13["verdict"] == "GO" else "review_migration")
    )
    blockers = list(hard_stop)
    if not model_probe_current:
        blockers.append("W14-B001-highest-model-not-verified")
    if not authorization.get("external_data_transfer_approved", False):
        blockers.append("W14-B002-external-review-data-transfer-not-approved")
    if queue_integrity["missing_assignments"] or queue_integrity["invalid_assignments"]:
        blockers.append("W14-B003-review-queue-migration-incomplete")
    if unresolved_review_count(state_counts):
        blockers.append("W14-B004-model-review-queue-open")
    if state_counts.get("blocked_by_deterministic_check", 0):
        blockers.append("W14-B005-deterministic-repair-queue-open")
    if week11["verdict"] != "GO":
        blockers.append("W14-B006-week11-dependency-chain")
    if week12["verdict"] != "GO":
        blockers.append("W14-B007-week12-gate")
    if week13["verdict"] != "GO":
        blockers.append("W14-B008-week13-full-evaluation-unavailable")
    if coverage_percent is None or coverage_percent < 85:
        blockers.append("W14-B009-coverage-below-85")
    if eval_result is None or eval_result.get("critical_failures") is None:
        blockers.append("W14-B010-eval-suite-unverified")
    else:
        if eval_result.get("critical_failures"):
            blockers.append("W14-B011-critical-eval-failures")
        if not eval_result.get("full_chain_coverage", False):
            blockers.append("W14-B013-eval-full-chain-coverage-incomplete")
    if resolution and not resolution.get("snapshot_pinned", False):
        blockers.append("W14-B012-model-version-alias-unpinned")
    return {
        "gate": "WEEK14_GATE",
        "verdict": "GO" if not blockers else "NO-GO",
        "mode": mode,
        "predecessors": {
            "week9": week9["verdict"],
            "week10": week10["verdict"],
            "week11": week11["verdict"],
            "week12": week12["verdict"],
            "week13": week13["verdict"],
        },
        "model_resolution": resolution,
        "external_data_transfer_approved": bool(
            authorization.get("external_data_transfer_approved")
        ),
        "precheck_findings": current_precheck_findings,
        "model_review_assignments": len(assignments),
        "review_queue_integrity": queue_integrity,
        "review_state_counts": state_counts,
        "evidence_breaks": evidence_breaks,
        "price_evidence_valid": price_evidence["valid"],
        "market_active_errors": market_counts["active_mapping_scope_errors"],
        "coverage_percent": coverage_percent,
        "full_tests_verified": full_tests_verified,
        "postgres_verified": postgres_tests_verified,
        "full_junit": full_junit,
        "postgres_junit": postgres_junit,
        "eval_result": (
            {
                key: eval_result.get(key)
                for key in (
                    "suite_code",
                    "suite_version",
                    "case_count",
                    "passed",
                    "failed",
                    "critical_failures",
                    "category_counts",
                    "full_chain_coverage",
                    "coverage_gaps",
                    "model_judge_executed",
                )
            }
            if eval_result is not None
            else None
        ),
        "hard_stop": hard_stop,
        "blocking_items": blockers,
        "customer_output_allowed": False if blockers else week12["customer_output_allowed"],
    }


def main() -> int:
    result = check_week14_gate()
    serialized = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    fingerprint = sha256(serialized.encode("utf-8")).hexdigest()[:12]
    report_dir = ROOT / "reports/week14_gate/runs" / f"run_{fingerprint}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "validation_results.json").write_text(serialized, encoding="utf-8")
    (report_dir / "gate_summary.md").write_text(
        "# Week 14 Gate\n\n"
        f"- Verdict: `{result['verdict']}`\n"
        f"- Mode: `{result['mode']}`\n"
        f"- Migrated review assignments: {result['model_review_assignments']}\n"
        f"- Pending model review: {result['review_state_counts'].get('pending_model_review', 0)}\n"
        f"- Deterministically blocked: {result['review_state_counts'].get('blocked_by_deterministic_check', 0)}\n"
        f"- Evidence chain breaks: {result['evidence_breaks']}\n"
        f"- Coverage: {result['coverage_percent']}%\n"
        "- No customer output is authorized while blockers remain.\n",
        encoding="utf-8",
    )
    (report_dir / "unresolved_blockers.md").write_text(
        "# Unresolved Blockers\n\n"
        + "\n".join(f"- `{item}`" for item in result["blocking_items"])
        + "\n",
        encoding="utf-8",
    )
    result["report_dir"] = str(report_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
