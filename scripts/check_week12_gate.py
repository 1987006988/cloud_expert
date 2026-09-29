from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
import yaml
from check_week11_gate import check_week11_gate
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from cloud_expert.database.models.decision import DecisionScenario
from cloud_expert.database.models.market import MarketCompatibilityAssessment, MarketContext
from cloud_expert.database.session import SessionLocal
from cloud_expert.market.validation import scan_market_integrity

ROOT = Path(__file__).resolve().parents[1]
REVIEW_AUTHORITY = ROOT / "config" / "review_authority.yaml"
REQUIRED_DOCS = (
    "docs/MARKET_MODE_ARCHITECTURE.md",
    "docs/PROVIDER_PARTITION_POLICY.md",
    "docs/MARKET_SCOPE_POLICY.md",
    "docs/SALES_OUTPUT_ARCHITECTURE.md",
)
REQUIRED_SCRIPTS = (
    "scripts/validate_market_scopes.py",
    "scripts/validate_market_partitions.py",
    "scripts/validate_regions.py",
    "scripts/validate_mapping_market_scope.py",
)
TEST_REPORT_DIR = ROOT / "reports" / "week12_gate"


def _junit_result(path: Path, *, max_age_days: int = 7) -> dict[str, Any] | None:
    if not path.exists() or time.time() - path.stat().st_mtime > max_age_days * 86400:
        return None
    try:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        return {
            "tests": sum(int(suite.get("tests", "0")) for suite in suites),
            "failures": sum(int(suite.get("failures", "0")) for suite in suites),
            "errors": sum(int(suite.get("errors", "0")) for suite in suites),
            "skipped": sum(int(suite.get("skipped", "0")) for suite in suites),
            "path": str(path),
        }
    except (ET.ParseError, OSError, ValueError):
        return None


def _verification_evidence() -> dict[str, Any]:
    full = _junit_result(TEST_REPORT_DIR / "full_junit.xml")
    postgres = _junit_result(TEST_REPORT_DIR / "postgres_junit.xml")
    coverage_path = TEST_REPORT_DIR / "coverage.json"
    coverage_percent: float | None = None
    if (
        full is not None
        and full["tests"] >= 100
        and full["failures"] == 0
        and full["errors"] == 0
        and coverage_path.exists()
        and abs(coverage_path.stat().st_mtime - Path(full["path"]).stat().st_mtime) < 120
    ):
        with suppress(OSError, ValueError, KeyError, TypeError):
            coverage_percent = float(
                json.loads(coverage_path.read_text(encoding="utf-8"))["totals"]["percent_covered"]
            )
    return {
        "full_suite": full,
        "postgres_suite": postgres,
        "coverage_percent": coverage_percent,
        "coverage_verified": coverage_percent is not None and coverage_percent >= 85,
        "postgres_verified": postgres is not None
        and postgres["tests"] >= 7
        and postgres["failures"] == 0
        and postgres["errors"] == 0
        and postgres["skipped"] == 0,
    }


def check_week12_development_authorization() -> dict[str, Any]:
    week11 = check_week11_gate()
    config = yaml.safe_load(REVIEW_AUTHORITY.read_text(encoding="utf-8"))
    readiness = week11["readiness"]
    internal_allowed = (
        config.get("authority") == "model_review"
        and config.get("authorized_by") == "project_owner"
        and config.get("scope") == "internal_engineering_only"
        and config.get("customer_output_approval") is False
        and config.get("preserve_legacy_human_history") is True
        and readiness["model_review_runs"] > 0
        and readiness["model_review_findings"] > 0
    )
    return {
        "week11_customer_gate": week11["verdict"],
        "week12_customer_gate": "NO-GO",
        "week12_internal_development": "AUTHORIZED" if internal_allowed else "BLOCKED",
        "review_authority": config.get("authority"),
        "model_review_findings": readiness["model_review_findings"],
        "customer_output_allowed": False,
        "unresolved_week11_blockers": week11["blocking_items"],
    }


def check_week12_gate() -> dict[str, Any]:
    development = check_week12_development_authorization()
    blockers: list[str] = []
    if development["week11_customer_gate"] != "GO":
        blockers.append("W12-B001-week11-gate")
    try:
        with SessionLocal() as session:
            market = scan_market_integrity(session)
            contexts = session.scalar(select(func.count()).select_from(MarketContext)) or 0
            assessments = (
                session.scalar(select(func.count()).select_from(MarketCompatibilityAssessment)) or 0
            )
            decision_market_modes = set(
                session.scalars(select(DecisionScenario.market_mode).distinct())
            )
    except SQLAlchemyError as exc:
        market = {"error": type(exc).__name__}
        contexts = 0
        assessments = 0
        decision_market_modes = set()
        blockers.append("W12-B002-market-schema-or-query")
    counts = market.get("counts", {})
    if any(
        counts.get(key, 0)
        for key in (
            "source_partition_missing",
            "region_partition_missing",
            "region_country_unknown",
            "active_mapping_scope_errors",
            "tco_product_market_mismatch",
            "price_product_region_market_mismatch",
            "price_evidence_partition_mismatch",
        )
    ):
        blockers.append("W12-B003-market-data-integrity")
    if market.get("customer_exposure_detected"):
        blockers.append("W12-B004-cross-market-customer-exposure")
    if contexts == 0 or assessments == 0:
        blockers.append("W12-B005-market-context-and-assessment-unpopulated")
    if not {"domestic", "international"}.issubset(decision_market_modes):
        blockers.append("W12-B010-dual-market-decision-scenarios-missing")
    missing_docs = [path for path in REQUIRED_DOCS if not (ROOT / path).exists()]
    missing_scripts = [path for path in REQUIRED_SCRIPTS if not (ROOT / path).exists()]
    if missing_docs:
        blockers.append("W12-B006-required-documents")
    if missing_scripts:
        blockers.append("W12-B007-validation-tools")
    verification = _verification_evidence()
    if not verification["coverage_verified"]:
        blockers.append(
            "W12-B008-coverage-below-85"
            if verification["coverage_percent"] is not None
            else "W12-B008-current-coverage-unverified"
        )
    if not verification["postgres_verified"]:
        blockers.append("W12-B009-current-postgres-unverified")
    return {
        "gate": "WEEK12_GATE",
        "verdict": "GO" if not blockers else "NO-GO",
        "week11_gate": development["week11_customer_gate"],
        "internal_development_authorized": development["week12_internal_development"],
        "customer_output_allowed": not blockers and development["week11_customer_gate"] == "GO",
        "market_integrity": market,
        "market_context_count": contexts,
        "market_compatibility_assessment_count": assessments,
        "decision_market_modes": sorted(decision_market_modes),
        "missing_required_docs": missing_docs,
        "missing_required_scripts": missing_scripts,
        "current_coverage_verified": verification["coverage_verified"],
        "current_postgres_verified": verification["postgres_verified"],
        "verification_evidence": verification,
        "blocking_items": blockers,
    }


def main() -> int:
    result = check_week12_gate()
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    fingerprint = sha256(serialized.encode("utf-8")).hexdigest()[:12]
    report_dir = ROOT / "reports" / "week12_gate" / "runs" / f"run_{fingerprint}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "validation_results.json").write_text(serialized, encoding="utf-8")
    (report_dir / "gate_summary.md").write_text(
        "# Week 12 Formal Gate\n\n"
        f"- Verdict: `{result['verdict']}`\n"
        f"- Week 11: `{result['week11_gate']}`\n"
        f"- Internal development: `{result['internal_development_authorized']}`\n"
        f"- Blockers: {len(result['blocking_items'])}\n",
        encoding="utf-8",
    )
    (report_dir / "unresolved_blockers.md").write_text(
        "# Unresolved Blockers\n\n"
        + "\n".join(f"- `{item}`" for item in result["blocking_items"])
        + "\n",
        encoding="utf-8",
    )
    result["report_dir"] = str(report_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
