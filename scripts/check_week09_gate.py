from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from check_week07_gate import check_week07_gate
from check_week08_gate import check_week08_gate
from sqlalchemy import func, select
from validate_cost_calculation_idempotency import validate_cost_calculation_idempotency
from validate_price_evidence import validate_price_evidence
from validate_price_skus import validate_price_skus
from validate_pricing_sources import validate_pricing_sources

from cloud_expert.database.models.evidence_package import EvidencePackage, EvidenceReference
from cloud_expert.database.session import SessionLocal
from cloud_expert.evidence_packages.validation import customer_output_eligibility_summary
from cloud_expert.quality.verification_receipts import (
    EXPECTED_HEAD,
    EXPECTED_POSTGRES_TEST_IDS,
    EXPECTED_PREVIOUS,
    read_gate_receipts,
)


def _verification_gates() -> tuple[dict[str, Any], dict[str, Any]]:
    context = Path(
        os.environ.get("CLOUD_EXPERT_GATE_RECEIPTS", ROOT / "tasks/verification_receipts.yaml")
    )
    receipts = read_gate_receipts(
        context,
        current_repo=ROOT,
        expected_test_ids=EXPECTED_POSTGRES_TEST_IDS,
        expected_head=EXPECTED_HEAD,
        expected_previous=EXPECTED_PREVIOUS,
    )
    coverage: dict[str, Any] = dict(receipts["coverage"])
    postgres: dict[str, Any] = dict(receipts["postgres"])
    percent = coverage["metrics"].get("coverage_percent")
    coverage.update(
        percent_covered=percent,
        threshold=85.0,
        passed=coverage["valid"]
        and coverage["current_code_verified"]
        and isinstance(percent, (float, int))
        and percent >= 85.0,
    )
    postgres["passed"] = postgres["valid"] and postgres["current_code_verified"]
    return coverage, postgres


def check_week09_gate() -> dict[str, Any]:
    week7 = check_week07_gate()
    week8 = check_week08_gate()
    pricing_sources = validate_pricing_sources()
    price_skus = validate_price_skus()
    price_evidence = validate_price_evidence()
    tco_validation = validate_cost_calculation_idempotency()
    coverage, postgres = _verification_gates()
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
    if not price_skus["valid"]:
        blockers.append("W9-B008-price-sku-snapshot")
    if not price_evidence["valid"]:
        blockers.append("W9-B009-price-evidence-chain")
    if not tco_validation["valid"]:
        blockers.append("W9-B010-tco-idempotency")

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
        "price_skus": price_skus,
        "price_evidence": price_evidence,
        "tco_validation": tco_validation,
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
