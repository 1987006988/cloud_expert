from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud_expert.database.enums import MappingLevel, ReviewStatus
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingFieldComparison,
    MappingRuleSet,
)


def validate_mapping_rules(session: Session) -> dict[str, Any]:
    rule_sets = session.scalars(select(MappingRuleSet)).all()
    errors: list[str] = []
    for rule_set in rule_sets:
        if not rule_set.rule_set_version:
            errors.append(f"rule_set_without_version:{rule_set.id}")
        if not rule_set.required_fields:
            errors.append(f"rule_set_without_required_fields:{rule_set.rule_set_code}")
    if not rule_sets:
        errors.append("no_mapping_rule_sets")
    return {"rule_sets": len(rule_sets), "errors": errors, "valid": not errors}


def validate_mapping_evidence(session: Session) -> dict[str, Any]:
    candidate_count = session.scalar(select(func.count()).select_from(MappingCandidate)) or 0
    candidates_with_evidence = (
        session.scalar(
            select(
                func.count(func.distinct(MappingCandidateEvidence.mapping_candidate_id))
            ).select_from(MappingCandidateEvidence)
        )
        or 0
    )
    missing = candidate_count - candidates_with_evidence
    approved_auto = (
        session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.review_status == ReviewStatus.HUMAN_REVIEWED.value)
        )
        or 0
    )
    return {
        "candidate_count": candidate_count,
        "candidates_with_evidence": candidates_with_evidence,
        "missing_evidence": missing,
        "auto_approved_candidates": approved_auto,
        "valid": candidate_count > 0 and missing == 0 and approved_auto == 0,
    }


def validate_mapping_idempotency(before: dict[str, int], after: dict[str, int]) -> dict[str, Any]:
    errors = [key for key, value in before.items() if after.get(key) != value]
    return {"before": before, "after": after, "errors": errors, "valid": not errors}


def mapping_counts(session: Session) -> dict[str, int]:
    return {
        "rule_sets": session.scalar(select(func.count()).select_from(MappingRuleSet)) or 0,
        "candidates": session.scalar(select(func.count()).select_from(MappingCandidate)) or 0,
        "product_candidates": session.scalar(
            select(func.count())
            .select_from(MappingCandidate)
            .where(MappingCandidate.mapping_level == MappingLevel.PRODUCT.value)
        )
        or 0,
        "field_comparisons": session.scalar(
            select(func.count()).select_from(MappingFieldComparison)
        )
        or 0,
        "evidence_links": session.scalar(select(func.count()).select_from(MappingCandidateEvidence))
        or 0,
    }
