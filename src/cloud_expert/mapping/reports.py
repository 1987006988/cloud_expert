from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import MappingCandidateStatus, MappingLevel, ReviewStatus
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingFieldComparison,
    MappingRuleSet,
)


def mapping_summary(session: Session) -> dict[str, Any]:
    by_level = {
        level: session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.mapping_level == level)
        )
        or 0
        for level in MappingLevel.values()
    }
    by_status = {
        status: session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.candidate_status == status)
        )
        or 0
        for status in MappingCandidateStatus.values()
    }
    candidates = list(session.scalars(select(MappingCandidate)).all())
    evidence_gap_candidates = sum(
        1
        for candidate in candidates
        if any("missing" in reason for reason in (candidate.blocking_reasons or []))
    )
    return {
        "rule_sets": session.scalar(select(func.count()).select_from(MappingRuleSet)) or 0,
        "candidates": session.scalar(select(func.count()).select_from(MappingCandidate)) or 0,
        "by_level": by_level,
        "by_status": by_status,
        "pending_review": session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.review_status == ReviewStatus.PENDING_REVIEW.value)
        )
        or 0,
        "approved": session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.review_status == ReviewStatus.HUMAN_REVIEWED.value)
        )
        or 0,
        "field_comparisons": session.scalar(
            select(func.count()).select_from(MappingFieldComparison)
        )
        or 0,
        "evidence_links": session.scalar(select(func.count()).select_from(MappingCandidateEvidence))
        or 0,
        "evidence_gap_candidates": evidence_gap_candidates,
    }


def write_mapping_reports(session: Session, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = mapping_summary(session)
    (output_dir / "mapping_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_markdown(output_dir / "product_mapping_summary.md", "Product Mapping Summary", summary)
    _write_markdown(
        output_dir / "compute_family_candidates.md", "Compute Family Candidates", summary
    )
    _write_markdown(output_dir / "compute_sku_candidates.md", "Compute SKU Candidates", summary)
    _write_markdown(
        output_dir / "object_storage_tier_candidates.md",
        "Object Storage Tier Candidates",
        summary,
    )
    _write_markdown(output_dir / "not_comparable_entities.md", "Not Comparable Entities", summary)
    _write_markdown(output_dir / "insufficient_evidence.md", "Insufficient Evidence", summary)
    _write_markdown(output_dir / "hard_exclusion_results.md", "Hard Exclusion Results", summary)
    _write_markdown(output_dir / "mapping_evidence_gaps.md", "Mapping Evidence Gaps", summary)
    _write_markdown(output_dir / "mapping_review_status.md", "Mapping Review Status", summary)
    _write_markdown(output_dir / "rule_coverage.md", "Rule Coverage", summary)
    return summary


def export_review_sample(session: Session, output_path: Path, limit: int = 200) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = session.scalars(
        select(MappingCandidate).order_by(MappingCandidate.id).limit(limit)
    ).all()
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "candidate_id",
                "market_mode",
                "mapping_level",
                "source_provider",
                "source_entity",
                "target_provider",
                "target_entity",
                "relationship_type",
                "candidate_level",
                "match_score",
                "confidence",
                "matched_fields",
                "different_fields",
                "missing_fields",
                "blocking_reasons",
                "conditions",
                "source_evidence",
                "target_evidence",
                "rule_set_version",
                "review_result",
                "reviewer",
                "reviewer_notes",
            ],
        )
        writer.writeheader()
        for candidate in rows:
            writer.writerow(
                {
                    "candidate_id": candidate.id,
                    "market_mode": candidate.rule_set.market_mode,
                    "mapping_level": candidate.mapping_level,
                    "source_provider": candidate.source_provider.code,
                    "source_entity": f"{candidate.source_entity_type}:{candidate.source_entity_id}",
                    "target_provider": candidate.target_provider.code,
                    "target_entity": f"{candidate.target_entity_type}:{candidate.target_entity_id}",
                    "relationship_type": candidate.relationship_type,
                    "candidate_level": candidate.candidate_status,
                    "match_score": candidate.normalized_score,
                    "confidence": candidate.confidence,
                    "matched_fields": "",
                    "different_fields": "",
                    "missing_fields": "",
                    "blocking_reasons": json.dumps(
                        candidate.blocking_reasons or [], ensure_ascii=False
                    ),
                    "conditions": json.dumps(candidate.conditions or [], ensure_ascii=False),
                    "source_evidence": "",
                    "target_evidence": "",
                    "rule_set_version": candidate.rule_set.rule_set_version,
                    "review_result": "",
                    "reviewer": "",
                    "reviewer_notes": "",
                }
            )
    return len(rows)


def _write_markdown(path: Path, title: str, summary: dict[str, Any]) -> None:
    lines = [
        f"# {title}",
        "",
        "Generated from versioned Week 7 mapping candidates. Candidates are not approved mappings.",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Rule sets | {summary['rule_sets']} |",
        f"| Candidates | {summary['candidates']} |",
        f"| Pending review | {summary['pending_review']} |",
        f"| Approved | {summary['approved']} |",
        f"| Field comparisons | {summary['field_comparisons']} |",
        f"| Evidence links | {summary['evidence_links']} |",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
