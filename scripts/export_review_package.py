import argparse
import csv
import io
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import ComparabilityStatus, ReviewItemStatus, ReviewStatus
from cloud_expert.database.models.canonical import (
    CanonicalFieldDefinition,
    ComparabilityAssessment,
    NormalizedSpecification,
)
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.review import DataQualityIssue, ReviewItem
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.session import SessionLocal
from cloud_expert.ingestion.storage.atomic_write import atomic_write_text

REVIEW_ITEM_HEADERS = [
    "id",
    "item_type",
    "severity",
    "status",
    "provider_code",
    "product_code",
    "field_code",
    "reason",
    "raw_value",
    "suggested_action",
    "source_url",
    "source_title",
    "locator",
    "excerpt",
    "reviewer_decision",
    "reviewer_notes",
]
NORMALIZED_HEADERS = [
    "id",
    "provider_code",
    "product_code",
    "canonical_field_code",
    "scope_type",
    "scope_identity",
    "default_scope_type",
    "value_qualifier",
    "canonical_value",
    "canonical_unit",
    "raw_value",
    "raw_unit",
    "quality_score",
    "review_status",
    "conversion_notes",
    "source_url",
    "source_title",
    "locator",
    "excerpt",
    "reviewer_decision",
    "reviewer_notes",
]
COMPARABILITY_HEADERS = [
    "id",
    "canonical_field_code",
    "source_provider_product",
    "target_provider_product",
    "scope_type",
    "value_qualifier",
    "status",
    "reason_code",
    "explanation",
    "market_scope",
    "evidence_coverage_score",
    "unit_compatibility_score",
    "qualifier_compatibility_score",
    "scope_compatibility_score",
    "overall_score",
    "review_status",
    "reviewer_decision",
    "reviewer_notes",
]
QUALITY_HEADERS = [
    "id",
    "provider_code",
    "product_code",
    "issue_type",
    "severity",
    "status",
    "field_code",
    "message",
    "source_url",
    "source_title",
    "locator",
    "excerpt",
    "reviewer_decision",
    "reviewer_notes",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export remediation human-review package.")
    parser.add_argument("--output-dir", type=Path, default=Path("D:/审核文件"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    with SessionLocal() as session:
        review_items = list(_review_item_rows(session))
        normalized_pending = list(_normalized_pending_rows(session))
        scope_mismatches = list(_scope_mismatch_rows(session))
        comparability_blockers = list(_comparability_blocker_rows(session))
        quality_issues = list(_quality_issue_rows(session))

    outputs = {
        "review_items_csv": args.output_dir / "review_items_open.csv",
        "review_items_json": args.output_dir / "review_items_open.json",
        "normalized_pending_csv": args.output_dir / "normalized_pending_review.csv",
        "normalized_pending_json": args.output_dir / "normalized_pending_review.json",
        "scope_mismatch_csv": args.output_dir / "scope_mismatch_review.csv",
        "scope_mismatch_json": args.output_dir / "scope_mismatch_review.json",
        "comparability_csv": args.output_dir / "comparability_blockers.csv",
        "comparability_json": args.output_dir / "comparability_blockers.json",
        "quality_csv": args.output_dir / "data_quality_issues_open.csv",
        "quality_json": args.output_dir / "data_quality_issues_open.json",
        "instructions": args.output_dir / "REVIEW_INSTRUCTIONS.md",
        "manifest": args.output_dir / "review_manifest.json",
    }
    _write_csv(outputs["review_items_csv"], REVIEW_ITEM_HEADERS, review_items)
    _write_json(outputs["review_items_json"], review_items)
    _write_csv(outputs["normalized_pending_csv"], NORMALIZED_HEADERS, normalized_pending)
    _write_json(outputs["normalized_pending_json"], normalized_pending)
    _write_csv(outputs["scope_mismatch_csv"], NORMALIZED_HEADERS, scope_mismatches)
    _write_json(outputs["scope_mismatch_json"], scope_mismatches)
    _write_csv(outputs["comparability_csv"], COMPARABILITY_HEADERS, comparability_blockers)
    _write_json(outputs["comparability_json"], comparability_blockers)
    _write_csv(outputs["quality_csv"], QUALITY_HEADERS, quality_issues)
    _write_json(outputs["quality_json"], quality_issues)

    manifest = {
        "generated_at": generated_at,
        "database_source": "DATABASE_URL",
        "output_dir": str(args.output_dir),
        "counts": {
            "review_items_open_or_in_review": len(review_items),
            "normalized_pending_review": len(normalized_pending),
            "scope_mismatch_review": len(scope_mismatches),
            "comparability_blockers": len(comparability_blockers),
            "data_quality_issues_open_or_in_review": len(quality_issues),
        },
        "files": {key: str(path) for key, path in outputs.items()},
    }
    atomic_write_text(outputs["manifest"], json.dumps(manifest, ensure_ascii=False, indent=2))
    atomic_write_text(outputs["instructions"], _instructions(manifest))
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return 0


def _review_item_rows(session: Session) -> Iterable[dict[str, str]]:
    statement = (
        select(ReviewItem, Evidence, SourceDocument)
        .outerjoin(Evidence, ReviewItem.evidence_id == Evidence.id)
        .outerjoin(SourceDocument, Evidence.source_document_id == SourceDocument.id)
        .where(
            ReviewItem.status.in_((ReviewItemStatus.OPEN.value, ReviewItemStatus.IN_REVIEW.value))
        )
        .order_by(ReviewItem.severity.desc(), ReviewItem.provider_code, ReviewItem.product_code)
    )
    for item, evidence, source in session.execute(statement):
        yield {
            "id": str(item.id),
            "item_type": item.item_type,
            "severity": item.severity,
            "status": item.status,
            "provider_code": item.provider_code or "",
            "product_code": item.product_code or "",
            "field_code": item.field_code or "",
            "reason": item.reason,
            "raw_value": item.raw_value or "",
            "suggested_action": item.suggested_action or "",
            **_source_columns(evidence, source),
            "reviewer_decision": "",
            "reviewer_notes": "",
        }


def _normalized_pending_rows(session: Session) -> Iterable[dict[str, str]]:
    statement = _normalized_statement().where(
        NormalizedSpecification.review_status == ReviewStatus.PENDING_REVIEW.value
    )
    for row in session.execute(statement):
        yield _normalized_row(*row)


def _scope_mismatch_rows(session: Session) -> Iterable[dict[str, str]]:
    statement = _normalized_statement().where(
        NormalizedSpecification.scope_type != CanonicalFieldDefinition.default_scope_type
    )
    for row in session.execute(statement):
        yield _normalized_row(*row)


def _normalized_statement() -> Any:
    return (
        select(
            NormalizedSpecification,
            CanonicalFieldDefinition,
            Product,
            Provider,
            Evidence,
            SourceDocument,
        )
        .join(
            CanonicalFieldDefinition,
            NormalizedSpecification.canonical_field_id == CanonicalFieldDefinition.id,
        )
        .join(Product, NormalizedSpecification.product_id == Product.id)
        .join(Provider, Product.provider_id == Provider.id)
        .join(Evidence, NormalizedSpecification.evidence_id == Evidence.id)
        .join(SourceDocument, Evidence.source_document_id == SourceDocument.id)
        .order_by(
            Provider.code, Product.code, CanonicalFieldDefinition.code, NormalizedSpecification.id
        )
    )


def _normalized_row(
    normalized: NormalizedSpecification,
    field: CanonicalFieldDefinition,
    product: Product,
    provider: Provider,
    evidence: Evidence,
    source: SourceDocument,
) -> dict[str, str]:
    return {
        "id": str(normalized.id),
        "provider_code": provider.code,
        "product_code": product.code,
        "canonical_field_code": field.code,
        "scope_type": normalized.scope_type,
        "scope_identity": normalized.scope_identity,
        "default_scope_type": field.default_scope_type,
        "value_qualifier": normalized.value_qualifier,
        "canonical_value": normalized.canonical_value or "",
        "canonical_unit": normalized.canonical_unit or "",
        "raw_value": normalized.raw_value,
        "raw_unit": normalized.raw_unit or "",
        "quality_score": str(normalized.quality_score or ""),
        "review_status": normalized.review_status,
        "conversion_notes": normalized.conversion_notes or "",
        **_source_columns(evidence, source),
        "reviewer_decision": "",
        "reviewer_notes": "",
    }


def _comparability_blocker_rows(session: Session) -> Iterable[dict[str, str]]:
    source_provider = Provider.__table__.alias("source_provider")
    target_provider = Provider.__table__.alias("target_provider")
    target_product = Product.__table__.alias("target_product")
    statement = (
        select(
            ComparabilityAssessment,
            CanonicalFieldDefinition,
            Product,
            source_provider.c.code,
            target_product.c.code,
            target_provider.c.code,
        )
        .join(
            CanonicalFieldDefinition,
            ComparabilityAssessment.canonical_field_id == CanonicalFieldDefinition.id,
        )
        .join(Product, ComparabilityAssessment.source_product_id == Product.id)
        .join(source_provider, Product.provider_id == source_provider.c.id)
        .join(
            target_product,
            ComparabilityAssessment.target_product_id == target_product.c.id,
        )
        .join(
            target_provider,
            target_product.c.provider_id == target_provider.c.id,
        )
        .where(
            ComparabilityAssessment.status != ComparabilityStatus.COMPARABLE.value,
        )
        .order_by(CanonicalFieldDefinition.code, ComparabilityAssessment.reason_code)
    )
    for (
        assessment,
        field,
        source_product,
        source_provider_code,
        target_code,
        target_provider_code,
    ) in session.execute(statement):
        yield {
            "id": str(assessment.id),
            "canonical_field_code": field.code,
            "source_provider_product": f"{source_provider_code}/{source_product.code}",
            "target_provider_product": f"{target_provider_code}/{target_code}",
            "scope_type": assessment.scope_type,
            "value_qualifier": assessment.value_qualifier,
            "status": assessment.status,
            "reason_code": assessment.reason_code,
            "explanation": assessment.explanation,
            "market_scope": assessment.market_scope or "",
            "evidence_coverage_score": str(assessment.evidence_coverage_score or ""),
            "unit_compatibility_score": str(assessment.unit_compatibility_score or ""),
            "qualifier_compatibility_score": str(assessment.qualifier_compatibility_score or ""),
            "scope_compatibility_score": str(assessment.scope_compatibility_score or ""),
            "overall_score": str(assessment.overall_score or ""),
            "review_status": assessment.review_status,
            "reviewer_decision": "",
            "reviewer_notes": "",
        }


def _quality_issue_rows(session: Session) -> Iterable[dict[str, str]]:
    statement = (
        select(DataQualityIssue, Evidence, SourceDocument)
        .outerjoin(Evidence, DataQualityIssue.evidence_id == Evidence.id)
        .outerjoin(SourceDocument, Evidence.source_document_id == SourceDocument.id)
        .where(
            DataQualityIssue.status.in_(
                (ReviewItemStatus.OPEN.value, ReviewItemStatus.IN_REVIEW.value)
            )
        )
        .order_by(DataQualityIssue.severity.desc(), DataQualityIssue.provider_code)
    )
    for issue, evidence, source in session.execute(statement):
        yield {
            "id": str(issue.id),
            "provider_code": issue.provider_code,
            "product_code": issue.product_code or "",
            "issue_type": issue.issue_type,
            "severity": issue.severity,
            "status": issue.status,
            "field_code": issue.field_code or "",
            "message": issue.message,
            **_source_columns(evidence, source),
            "reviewer_decision": "",
            "reviewer_notes": "",
        }


def _source_columns(
    evidence: Evidence | None,
    source: SourceDocument | None,
) -> dict[str, str]:
    return {
        "source_url": "" if source is None else source.url,
        "source_title": "" if source is None else source.title,
        "locator": "" if evidence is None else evidence.locator,
        "excerpt": "" if evidence is None else evidence.excerpt,
    }


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, handle.getvalue())


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, json.dumps(rows, ensure_ascii=False, indent=2, default=str))


def _instructions(manifest: dict[str, Any]) -> str:
    counts = manifest["counts"]
    return f"""# Human Review Package

Generated at: `{manifest["generated_at"]}`

Review these files before Week 7 product mapping:

| File | Rows | Purpose |
| --- | ---: | --- |
| `review_items_open.csv` | {counts["review_items_open_or_in_review"]} | Parser and data-quality items explicitly queued for human review. |
| `normalized_pending_review.csv` | {counts["normalized_pending_review"]} | Canonical normalized values whose machine status is still pending review. |
| `scope_mismatch_review.csv` | {counts["scope_mismatch_review"]} | Normalized values whose actual scope differs from canonical default scope. |
| `comparability_blockers.csv` | {counts["comparability_blockers"]} | Field-level comparability assessments that are not `comparable`. |
| `data_quality_issues_open.csv` | {counts["data_quality_issues_open_or_in_review"]} | Open/in-review quality issues. |

Fill `reviewer_decision` and `reviewer_notes` in the CSVs. Accepted decisions
should be traceable to the linked `source_url`, `locator`, and `excerpt`.
Do not treat these rows as customer-facing claims until they are reviewed and
the database is updated in a later remediation pass.
"""


if __name__ == "__main__":
    raise SystemExit(main())
