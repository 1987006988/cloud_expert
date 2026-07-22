import argparse
import json
from collections.abc import Mapping, Sequence

import _bootstrap  # noqa: F401
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.specification import ProductSpecification
from cloud_expert.database.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Relink existing normalized rows and evidence rows to their provenance chain."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without committing.")
    args = parser.parse_args()

    with SessionLocal() as session:
        result = relink_normalized_evidence(session, dry_run=args.dry_run)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["unresolved_total"] == 0 else 1


def relink_normalized_evidence(session: Session, *, dry_run: bool) -> dict[str, object]:
    evidence_result = _relink_evidence_snapshots(session)
    normalized_result = _relink_normalized_rows(session)
    unresolved_total = _counter(evidence_result, "unresolved") + _counter(
        normalized_result,
        "unresolved",
    )
    return {
        "dry_run": dry_run,
        "evidence_snapshots": evidence_result,
        "normalized_evidence": normalized_result,
        "unresolved_total": unresolved_total,
    }


def _relink_evidence_snapshots(session: Session) -> dict[str, object]:
    checked = 0
    relinked = 0
    unresolved = 0
    samples: list[dict[str, object]] = []
    evidence_rows = session.scalars(
        select(Evidence).where(Evidence.snapshot_record_id.is_(None)).order_by(Evidence.id)
    )
    for evidence in evidence_rows:
        checked += 1
        source_document = session.get(SourceDocument, evidence.source_document_id)
        if source_document is None:
            unresolved += 1
            _sample(samples, evidence.id, "missing_source_document")
            continue
        candidates = _candidate_snapshots(session, evidence, source_document)
        if len(candidates) == 1:
            evidence.snapshot_record_id = candidates[0].id
            relinked += 1
            continue
        unresolved += 1
        reason = "no_candidate_snapshot" if not candidates else "ambiguous_candidate_snapshot"
        _sample(samples, evidence.id, reason)
    return {
        "checked": checked,
        "relinked": relinked,
        "unresolved": unresolved,
        "samples": samples,
    }


def _candidate_snapshots(
    session: Session,
    evidence: Evidence,
    source_document: SourceDocument,
) -> Sequence[SnapshotRecord]:
    candidates: list[SnapshotRecord] = []
    for content_hash in (evidence.content_hash, source_document.content_hash):
        if not content_hash:
            continue
        candidates = list(
            session.scalars(
                select(SnapshotRecord)
                .where(
                    SnapshotRecord.source_document_id == source_document.id,
                    SnapshotRecord.content_hash == content_hash,
                )
                .order_by(SnapshotRecord.id)
            )
        )
        if len(candidates) == 1:
            return candidates

    if source_document.storage_path:
        candidates = list(
            session.scalars(
                select(SnapshotRecord)
                .where(
                    SnapshotRecord.source_document_id == source_document.id,
                    SnapshotRecord.storage_path == source_document.storage_path,
                )
                .order_by(SnapshotRecord.id)
            )
        )
        if len(candidates) == 1:
            return candidates

    candidates = list(
        session.scalars(
            select(SnapshotRecord)
            .where(SnapshotRecord.source_document_id == source_document.id)
            .order_by(SnapshotRecord.id)
        )
    )
    return candidates if len(candidates) == 1 else []


def _relink_normalized_rows(session: Session) -> dict[str, object]:
    checked = 0
    relinked = 0
    unresolved = 0
    samples: list[dict[str, object]] = []
    normalized_rows = session.scalars(
        select(NormalizedSpecification).order_by(NormalizedSpecification.id)
    )
    for normalized in normalized_rows:
        checked += 1
        specification = session.get(ProductSpecification, normalized.product_specification_id)
        if specification is None:
            unresolved += 1
            _sample(samples, normalized.id, "missing_product_specification")
            continue
        if normalized.evidence_id == specification.evidence_id:
            continue
        evidence = session.get(Evidence, specification.evidence_id)
        if evidence is None:
            unresolved += 1
            _sample(samples, normalized.id, "missing_specification_evidence")
            continue
        normalized.evidence_id = specification.evidence_id
        relinked += 1
    return {
        "checked": checked,
        "relinked": relinked,
        "unresolved": unresolved,
        "samples": samples,
    }


def _sample(samples: list[dict[str, object]], row_id: int, reason: str) -> None:
    if len(samples) < 20:
        samples.append({"id": row_id, "reason": reason})


def _counter(result: Mapping[str, object], key: str) -> int:
    value = result[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} is not an integer counter")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
