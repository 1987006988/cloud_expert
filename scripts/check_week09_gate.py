from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT
from check_week07_gate import check_week07_gate
from check_week08_gate import check_week08_gate
from sqlalchemy import func, select
from validate_pricing_sources import validate_pricing_sources

from cloud_expert.database.models.evidence_package import EvidencePackage, EvidenceReference
from cloud_expert.database.session import SessionLocal
from cloud_expert.evidence_packages.validation import customer_output_eligibility_summary


def _coverage_gate() -> dict[str, Any]:
    coverage_path = ROOT / "reports" / "remediation" / "stage2" / "coverage.json"
    if not coverage_path.exists():
        return {"coverage_json": str(coverage_path), "percent_covered": None, "passed": False}
    data = json.loads(coverage_path.read_text(encoding="utf-8"))
    percent = data.get("totals", {}).get("percent_covered")
    return {
        "coverage_json": str(coverage_path),
        "percent_covered": percent,
        "threshold": 85.0,
        "passed": percent is not None and percent >= 85.0,
    }


def _postgres_gate() -> dict[str, Any]:
    validation_path = (
        ROOT / "reports" / "remediation" / "r011" / "runs" / "run_02" / "validation_results.json"
    )
    if not validation_path.exists():
        return {"validation_report": str(validation_path), "passed": False}
    data = json.loads(validation_path.read_text(encoding="utf-8"))
    tests = data.get("tests", {})
    postgres = data.get("postgres", {})
    return {
        "validation_report": str(validation_path),
        "r011_status": data.get("r011_status"),
        "postgres_version": postgres.get("server_version"),
        "pytest_postgres_passed": tests.get("pytest_postgres_passed"),
        "pytest_integration_passed": tests.get("pytest_integration_passed"),
        "passed": data.get("r011_status") == "COMPLETED"
        and tests.get("pytest_postgres_passed", 0) >= 6
        and tests.get("pytest_integration_passed", 0) >= 6,
    }


def check_week09_gate() -> dict[str, Any]:
    week7 = check_week07_gate()
    week8 = check_week08_gate()
    pricing_sources = validate_pricing_sources()
    coverage = _coverage_gate()
    postgres = _postgres_gate()
    with SessionLocal() as session:
        packages = session.scalar(select(func.count()).select_from(EvidencePackage)) or 0
        references = session.scalar(select(func.count()).select_from(EvidenceReference)) or 0
        eligibility = customer_output_eligibility_summary(session)

    blockers: list[str] = []
    if week7["verdict"] != "GO":
        blockers.append("W9-B001-week7-gate")
    if week8["verdict"] != "GO":
        blockers.append("W9-B002-week8-gate")
    if packages == 0 or references == 0:
        blockers.append("W9-B003-evidence-package")
    if not eligibility["valid"]:
        blockers.append("W9-B004-customer-output-eligibility")
    if not coverage["passed"]:
        blockers.append("W9-B005-coverage")
    if not postgres["passed"]:
        blockers.append("W9-B006-postgresql")
    if not pricing_sources["valid"]:
        blockers.append("W9-B007-pricing-source-readiness")

    return {
        "gate": "WEEK9_GATE",
        "verdict": "GO" if not blockers else "NO-GO",
        "week7_gate": week7,
        "week8_gate": week8,
        "evidence_packages": packages,
        "evidence_references": references,
        "customer_output_eligibility": eligibility,
        "coverage": coverage,
        "postgres": postgres,
        "pricing_sources": pricing_sources,
        "blocking_items": blockers,
        "notes": [
            "Pricing/TCO business code must not run while pricing source readiness is false.",
            "Missing prices must remain missing; they must not be treated as zero.",
        ],
    }


def main() -> int:
    result = check_week09_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
