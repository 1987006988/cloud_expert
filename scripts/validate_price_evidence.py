from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import SourceType
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.aliyun_promotion import RULE as CATALOG_RULE
from cloud_expert.pricing.aliyun_promotion import catalog_price_valid
from cloud_expert.pricing.consumption import aws_price_disposition
from cloud_expert.pricing.huawei_promotion import RULE, bounded_quote_valid


def validate_price_evidence() -> dict[str, Any]:
    with SessionLocal() as session:
        aws_dispositions = [
            aws_price_disposition(session, price)
            for price in session.scalars(
                select(PriceSnapshot)
                .join(Evidence)
                .join(PriceSKU, PriceSnapshot.price_sku_id == PriceSKU.id)
                .join(Provider, PriceSKU.provider_id == Provider.id)
                .where((Provider.code == "aws") | Evidence.parser_rule.startswith("aws_"))
            )
        ]
        invalid_aws_catalog_prices = [
            item.price_id for item in aws_dispositions if item.status == "blocked"
        ]
        invalid_catalog_prices = [
            price.id
            for price in session.scalars(
                select(PriceSnapshot).join(Evidence).where(Evidence.parser_rule == CATALOG_RULE)
            )
            if not catalog_price_valid(session, price)
        ]
        invalid_bounded_prices = [
            price.id
            for price in session.scalars(
                select(PriceSnapshot).join(Evidence).where(Evidence.parser_rule == RULE)
            )
            if not bounded_quote_valid(session, price)
        ]
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
    if invalid_bounded_prices:
        errors.append("bounded price supporting evidence or quantity scope is invalid")
    if invalid_catalog_prices:
        errors.append("catalog reference supporting evidence or quantity scope is invalid")
    if invalid_aws_catalog_prices:
        errors.append(
            "AWS catalog tiers, raw hashes, policy evidence or persisted prices are invalid"
        )
    completeness = 0 if snapshots == 0 else linked_to_pricing_source / snapshots
    return {
        "price_snapshots": snapshots,
        "linked_to_evidence": linked_to_evidence,
        "linked_to_pricing_source": linked_to_pricing_source,
        "missing_snapshot_record": missing_snapshot_record,
        "invalid_bounded_prices": invalid_bounded_prices,
        "invalid_catalog_prices": invalid_catalog_prices,
        "invalid_aws_catalog_prices": invalid_aws_catalog_prices,
        "historical_superseded_aws_prices": [
            item.price_id for item in aws_dispositions if item.status == "superseded"
        ],
        "currently_unusable_aws_prices": [
            item.price_id for item in aws_dispositions if item.status != "current"
        ],
        "aws_price_dispositions": [item.model_dump(mode="json") for item in aws_dispositions],
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
