from __future__ import annotations

import json

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.models.market import MarketCompatibilityAssessment, MarketContext
from cloud_expert.database.session import SessionLocal
from cloud_expert.market.validation import scan_market_integrity


def validate_market_scopes() -> dict[str, object]:
    with SessionLocal() as session:
        integrity = scan_market_integrity(session)
        contexts = session.scalar(select(func.count()).select_from(MarketContext)) or 0
        assessments = (
            session.scalar(select(func.count()).select_from(MarketCompatibilityAssessment)) or 0
        )
    counts = integrity["counts"]
    blocking_fields = (
        "source_partition_missing",
        "region_partition_missing",
        "region_country_unknown",
        "active_mapping_scope_errors",
        "tco_product_market_mismatch",
        "price_product_region_market_mismatch",
        "price_evidence_partition_mismatch",
        "price_evidence_partition_missing",
    )
    blockers = [key for key in blocking_fields if counts[key]]
    if contexts == 0:
        blockers.append("market_context_missing")
    if assessments == 0:
        blockers.append("market_compatibility_assessment_missing")
    if integrity["customer_exposure_detected"]:
        blockers.append("cross_market_customer_exposure")
    return {
        "market_contexts": contexts,
        "market_compatibility_assessments": assessments,
        "integrity": integrity,
        "blockers": blockers,
        "valid": not blockers,
    }


def main() -> int:
    result = validate_market_scopes()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
