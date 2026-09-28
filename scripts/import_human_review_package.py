from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from _bootstrap import ROOT
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import ReviewItemStatus, ReviewStatus
from cloud_expert.database.models.canonical import ComparabilityAssessment, NormalizedSpecification
from cloud_expert.database.models.parsing import ParsedFieldCandidate
from cloud_expert.database.models.product_extension import ProductSLA
from cloud_expert.database.models.review import (
    DataQualityIssue,
    HumanReviewDecision,
    HumanReviewImportBatch,
    ReviewItem,
)
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.session import SessionLocal

PACKAGE_FILES = {
    "review_items": "review_items_reviewed.csv",
    "normalized_pending": "normalized_pending_review_reviewed.csv",
    "scope_mismatch": "scope_mismatch_reviewed.csv",
    "comparability_blockers": "comparability_blockers_reviewed.csv",
    "data_quality_issues": "data_quality_issues_reviewed.csv",
}
ACCEPT_DECISIONS = {"accept", "accept_with_conditions"}
REPARSE_DECISION = "reject_reparse"
DEFER_DECISION = "defer"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(zip_file: zipfile.ZipFile, name: str) -> Any:
    try:
        with zip_file.open(name) as handle:
            return json.loads(handle.read().decode("utf-8"))
    except KeyError:
        return None


def _read_csv(zip_file: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    try:
        with zip_file.open(name) as handle:
            text = handle.read().decode("utf-8-sig")
    except KeyError:
        return []
    if not text.strip():
        return []
    return [dict(row) for row in csv.DictReader(text.splitlines()) if any(row.values())]


def _model_snapshot(obj: Any) -> dict[str, Any] | None:
    if obj is None:
        return None
    columns = obj.__table__.columns
    payload: dict[str, Any] = {}
    for column in columns:
        value = getattr(obj, column.name)
        payload[column.name] = _json_safe(value)
    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _as_int(value: str | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    return int(str(value).strip())


def _review_item_target(session: Session, row: dict[str, str]) -> ReviewItem | None:
    row_id = _as_int(row.get("id"))
    return session.get(ReviewItem, row_id) if row_id is not None else None


def _normalized_target(session: Session, row: dict[str, str]) -> NormalizedSpecification | None:
    row_id = _as_int(row.get("id"))
    return session.get(NormalizedSpecification, row_id) if row_id is not None else None


def _comparability_target(session: Session, row: dict[str, str]) -> ComparabilityAssessment | None:
    row_id = _as_int(row.get("id"))
    return session.get(ComparabilityAssessment, row_id) if row_id is not None else None


def _quality_target(session: Session, row: dict[str, str]) -> DataQualityIssue | None:
    row_id = _as_int(row.get("id"))
    return session.get(DataQualityIssue, row_id) if row_id is not None else None


def _apply_review_item(
    session: Session,
    item: ReviewItem | None,
    decision: str,
    reviewer: str,
    reviewed_at: datetime,
) -> str:
    if item is None:
        return "missing_target"
    if decision in ACCEPT_DECISIONS:
        item.status = ReviewItemStatus.RESOLVED.value
        item.resolved_by = reviewer
        item.resolved_at = reviewed_at
        if item.parsed_field_candidate_id is not None:
            parsed = session.get(ParsedFieldCandidate, item.parsed_field_candidate_id)
            if parsed is not None:
                parsed.review_status = ReviewStatus.HUMAN_REVIEWED.value
        if item.evidence_id is not None:
            evidence = session.get(Evidence, item.evidence_id)
            if evidence is not None:
                evidence.review_status = ReviewStatus.HUMAN_REVIEWED.value
                evidence.reviewed_by = reviewer
                evidence.reviewed_at = reviewed_at
        return "applied"
    if decision == REPARSE_DECISION:
        item.status = ReviewItemStatus.IN_REVIEW.value
        item.suggested_action = "reject_reparse imported; queued for parser remediation."
        if item.parsed_field_candidate_id is not None:
            parsed = session.get(ParsedFieldCandidate, item.parsed_field_candidate_id)
            if parsed is not None:
                parsed.review_status = ReviewStatus.REJECTED.value
        if item.evidence_id is not None and item.field_code == "sla.availability_percentage":
            for sla in session.scalars(
                select(ProductSLA).where(ProductSLA.evidence_id == item.evidence_id)
            ):
                sla.review_status = ReviewStatus.REJECTED.value
        return "queued_reparse"
    if decision == DEFER_DECISION:
        item.status = ReviewItemStatus.IN_REVIEW.value
        return "deferred"
    return "ignored_unknown_decision"


def _apply_normalized(
    row: NormalizedSpecification | None,
    decision: str,
) -> str:
    if row is None:
        return "missing_target"
    if decision in ACCEPT_DECISIONS:
        row.review_status = ReviewStatus.HUMAN_REVIEWED.value
        return "applied"
    if decision == REPARSE_DECISION:
        row.review_status = ReviewStatus.REJECTED.value
        return "queued_reparse"
    if decision == DEFER_DECISION:
        row.review_status = ReviewStatus.PENDING_REVIEW.value
        return "deferred"
    return "ignored_unknown_decision"


def _apply_comparability(
    row: ComparabilityAssessment | None,
    decision: str,
) -> str:
    if row is None:
        return "missing_target"
    if decision in ACCEPT_DECISIONS:
        row.review_status = ReviewStatus.HUMAN_REVIEWED.value
        return "applied"
    if decision == REPARSE_DECISION:
        row.review_status = ReviewStatus.REJECTED.value
        return "queued_reparse"
    if decision == DEFER_DECISION:
        row.review_status = ReviewStatus.PENDING_REVIEW.value
        return "deferred"
    return "ignored_unknown_decision"


def _apply_quality(
    row: DataQualityIssue | None,
    decision: str,
) -> str:
    if row is None:
        return "missing_target"
    if decision in ACCEPT_DECISIONS:
        row.status = ReviewItemStatus.RESOLVED.value
        return "applied"
    if decision == REPARSE_DECISION:
        row.status = ReviewItemStatus.IN_REVIEW.value
        return "queued_reparse"
    if decision == DEFER_DECISION:
        row.status = ReviewItemStatus.IN_REVIEW.value
        return "deferred"
    return "ignored_unknown_decision"


def _target_for_area(session: Session, area: str, row: dict[str, str]) -> tuple[str, Any | None]:
    if area == "review_items":
        return "review_item", _review_item_target(session, row)
    if area in {"normalized_pending", "scope_mismatch"}:
        return "normalized_specification", _normalized_target(session, row)
    if area == "comparability_blockers":
        return "comparability_assessment", _comparability_target(session, row)
    if area == "data_quality_issues":
        return "data_quality_issue", _quality_target(session, row)
    return area, None


def _apply_area(
    session: Session,
    area: str,
    target: Any | None,
    decision: str,
    reviewer: str,
    reviewed_at: datetime,
) -> str:
    if area == "review_items":
        return _apply_review_item(session, target, decision, reviewer, reviewed_at)
    if area in {"normalized_pending", "scope_mismatch"}:
        return _apply_normalized(target, decision)
    if area == "comparability_blockers":
        return _apply_comparability(target, decision)
    if area == "data_quality_issues":
        return _apply_quality(target, decision)
    return "ignored_unknown_area"


def import_review_package(
    package_path: Path,
    *,
    reviewer: str,
    imported_at: datetime | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    imported_at = imported_at or datetime.now(UTC)
    package_hash = _sha256(package_path)
    batch_code = f"human_review_{package_hash[:12]}"
    output_dir = (
        output_dir or ROOT / "reports" / "remediation" / "week11_review_import" / batch_code
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    archived_package = output_dir / package_path.name
    if not archived_package.exists():
        shutil.copy2(package_path, archived_package)

    with zipfile.ZipFile(package_path) as zip_file:
        review_summary = _read_json(zip_file, "review_summary.json") or {}
        manifest = _read_json(zip_file, "reviewed_manifest.json") or {}
        rows_by_area = {
            area: _read_csv(zip_file, filename) for area, filename in PACKAGE_FILES.items()
        }

    total_rows = sum(len(rows) for rows in rows_by_area.values())
    counters: Counter[str] = Counter()
    area_counts: dict[str, Counter[str]] = {}

    with SessionLocal() as session:
        existing = session.scalar(
            select(HumanReviewImportBatch).where(HumanReviewImportBatch.batch_code == batch_code)
        )
        if existing is not None:
            payload = {
                "valid": True,
                "already_imported": True,
                "batch_code": existing.batch_code,
                "batch_id": existing.id,
                "package_sha256": existing.package_sha256,
                "total_rows": existing.total_rows,
            }
            (output_dir / "import_results.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            return payload

        batch = HumanReviewImportBatch(
            batch_code=batch_code,
            package_path=str(archived_package),
            package_sha256=package_hash,
            imported_by=reviewer,
            imported_at=imported_at,
            status="importing",
            total_rows=total_rows,
            applied_rows=0,
            rejected_for_reparse_rows=0,
            deferred_rows=0,
            summary_json={
                "review_summary": review_summary,
                "reviewed_manifest": manifest,
            },
            notes="Controlled Week 11 import of completed human review package.",
        )
        session.add(batch)
        session.flush()

        for area, rows in rows_by_area.items():
            area_counter: Counter[str] = Counter()
            for row in rows:
                decision = (row.get("reviewer_decision") or "").strip()
                source_row_id = (row.get("id") or "").strip()
                target_table, target = _target_for_area(session, area, row)
                before = _model_snapshot(target)
                action_status = _apply_area(session, area, target, decision, reviewer, imported_at)
                after = _model_snapshot(target)
                decision_row = HumanReviewDecision(
                    batch_id=batch.id,
                    review_area=area,
                    source_row_id=source_row_id,
                    target_table=target_table,
                    target_id=None if target is None else target.id,
                    reviewer_decision=decision,
                    reviewer=reviewer,
                    reviewed_at=imported_at,
                    reviewer_notes=row.get("reviewer_notes") or None,
                    before_json=before,
                    after_json=after,
                    action_status=action_status,
                )
                session.add(decision_row)
                counters[decision] += 1
                counters[action_status] += 1
                area_counter[decision] += 1
                area_counter[action_status] += 1
            area_counts[area] = area_counter

        batch.status = "completed"
        batch.applied_rows = counters["applied"]
        batch.rejected_for_reparse_rows = counters["queued_reparse"]
        batch.deferred_rows = counters["deferred"]
        session.commit()
        batch_id = batch.id

    payload = {
        "valid": True,
        "already_imported": False,
        "batch_code": batch_code,
        "batch_id": batch_id,
        "package_sha256": package_hash,
        "archived_package": str(archived_package),
        "total_rows": total_rows,
        "decision_counts": dict(counters),
        "area_counts": {area: dict(counter) for area, counter in area_counts.items()},
        "database_update_required_from_package": review_summary.get("database_update_required"),
        "customer_facing_ready_from_package": review_summary.get("customer_facing_ready"),
    }
    (output_dir / "import_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / "import_summary.md").write_text(
        "\n".join(
            [
                "# Human Review Import Summary",
                "",
                f"- Batch: `{batch_code}`",
                f"- Package SHA256: `{package_hash}`",
                f"- Total rows: {total_rows}",
                f"- Applied rows: {counters['applied']}",
                f"- Queued reparse rows: {counters['queued_reparse']}",
                f"- Deferred rows: {counters['deferred']}",
                f"- Missing target rows: {counters['missing_target']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a completed human-review package.")
    parser.add_argument("package", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    result = import_review_package(
        args.package,
        reviewer=args.reviewer,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
