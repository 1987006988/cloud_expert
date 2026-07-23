from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from _bootstrap import ROOT as _ROOT  # noqa: F401
from sqlalchemy import func, select

from cloud_expert.database.enums import SourceType
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.registry.loader import load_registry_entries

REQUIRED_PRICING_SOURCES = {
    ("huawei_cloud", "ecs"),
    ("huawei_cloud", "obs"),
    ("aws", "ec2"),
    ("aws", "s3"),
    ("aliyun", "ecs"),
    ("aliyun", "oss"),
}


def validate_pricing_sources() -> dict[str, Any]:
    entries = [
        entry for entry in load_registry_entries() if entry.source_type == SourceType.PRICING.value
    ]
    registered = {(entry.provider_code, entry.product_code or "") for entry in entries}
    missing_required = sorted(
        f"{provider}/{product}"
        for provider, product in REQUIRED_PRICING_SOURCES
        if (provider, product) not in registered
    )
    by_provider = Counter(entry.provider_code for entry in entries)
    disabled = [entry.source_id for entry in entries if not entry.enabled]
    manual_only = [entry.source_id for entry in entries if entry.manual_only]
    automated_fetchable = [
        entry.source_id for entry in entries if entry.enabled and entry.allow_automated_fetch
    ]
    terms_not_approved = [
        entry.source_id for entry in entries if entry.terms_review_status != "approved"
    ]

    with SessionLocal() as session:
        source_documents = (
            session.scalar(
                select(func.count())
                .select_from(SourceDocument)
                .where(SourceDocument.source_type == SourceType.PRICING.value)
            )
            or 0
        )
        evidence = (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .join(SourceDocument, Evidence.source_document_id == SourceDocument.id)
                .where(SourceDocument.source_type == SourceType.PRICING.value)
            )
            or 0
        )

    errors: list[str] = []
    if missing_required:
        errors.append("missing required provider/product pricing registry entries")
    if source_documents == 0:
        errors.append("no pricing SourceDocument rows are present")
    if evidence == 0:
        errors.append("no pricing Evidence rows are present")
    if not automated_fetchable:
        errors.append("no enabled automated pricing source is available")

    return {
        "required_provider_products": sorted(
            f"{provider}/{product}" for provider, product in REQUIRED_PRICING_SOURCES
        ),
        "registered_pricing_sources": len(entries),
        "registered_by_provider": dict(sorted(by_provider.items())),
        "missing_required": missing_required,
        "disabled_sources": disabled,
        "manual_only_sources": manual_only,
        "automated_fetchable_sources": automated_fetchable,
        "terms_not_approved": terms_not_approved,
        "pricing_source_documents": source_documents,
        "pricing_evidence": evidence,
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Week 9 official pricing source readiness."
    )
    parser.add_argument("--allow-empty-documents", action="store_true")
    args = parser.parse_args()
    result = validate_pricing_sources()
    if args.allow_empty_documents:
        result["errors"] = [
            error
            for error in result["errors"]
            if error
            not in {
                "no pricing SourceDocument rows are present",
                "no pricing Evidence rows are present",
            }
        ]
        result["valid"] = not result["errors"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
