from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import SourceType
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.session import SessionLocal


def validate_price_evidence() -> dict[str, Any]:
    with SessionLocal() as session:
        snapshots = session.scalar(select(func.count()).select_from(PriceSnapshot)) or 0
        linked_to_evidence = (
            session.scalar(
                select(func.count())
                .select_from(PriceSnapshot)
                .join(Evidence, PriceSnapshot.evidence_id == Evidence.id)
            )
            or 0
        )
        linked_to_pricing_source = (
            session.scalar(
                select(func.count())
                .select_from(PriceSnapshot)
                .join(Evidence, PriceSnapshot.evidence_id == Evidence.id)
                .join(SourceDocument, Evidence.source_document_id == SourceDocument.id)
                .where(SourceDocument.source_type == SourceType.PRICING.value)
            )
            or 0
        )
        missing_snapshot_record = (
            session.scalar(
                select(func.count())
                .select_from(PriceSnapshot)
                .join(Evidence, PriceSnapshot.evidence_id == Evidence.id)
                .where(Evidence.snapshot_record_id.is_(None))
            )
            or 0
        )
    errors: list[str] = []
    if snapshots == 0:
        errors.append("no PriceSnapshot rows are present")
    if linked_to_evidence != snapshots:
        errors.append("one or more PriceSnapshot rows do not resolve to Evidence")
    if linked_to_pricing_source != snapshots:
        errors.append("one or more PriceSnapshot rows do not resolve to pricing SourceDocument")
    if missing_snapshot_record:
        errors.append("one or more price Evidence rows lack SnapshotRecord")
    completeness = 0 if snapshots == 0 else linked_to_pricing_source / snapshots
    return {
        "price_snapshots": snapshots,
        "linked_to_evidence": linked_to_evidence,
        "linked_to_pricing_source": linked_to_pricing_source,
        "missing_snapshot_record": missing_snapshot_record,
        "price_evidence_completeness": completeness,
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    result = validate_price_evidence()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
