from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Decision(StrEnum):
    APPROVED = "model_approved"
    CONDITIONAL = "model_approved_with_conditions"
    REPARSE = "model_rejected_reparse"
    INCONCLUSIVE = "model_inconclusive"
    BLOCKED = "model_blocked"


class StrictReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrimaryReview(StrictReviewModel):
    decision: Decision
    confidence: float = Field(ge=0, le=1)
    supported_by_evidence: bool
    field_semantics_correct: bool
    scope_correct: bool
    market_scope_correct: bool
    conditions: list[str]
    blocking_reasons: list[str]
    required_repairs: list[str]
    evidence_references: list[int]
    reasoning_summary: str


class AdversarialReview(StrictReviewModel):
    verdict: str = Field(pattern="^(agree|disagree|uncertain)$")
    identified_errors: list[str]
    missing_conditions: list[str]
    recommended_decision: Decision
    confidence: float = Field(ge=0, le=1)
    evidence_references: list[int]
    reasoning_summary: str


def validate_review_evidence(
    review: PrimaryReview | AdversarialReview, allowed_ids: set[int]
) -> None:
    if not set(review.evidence_references).issubset(allowed_ids):
        raise ValueError("model cited evidence outside the review input")
    if isinstance(review, PrimaryReview) and review.decision in {
        Decision.APPROVED,
        Decision.CONDITIONAL,
    }:
        if not review.supported_by_evidence or not review.evidence_references:
            raise ValueError("approval requires cited, supporting evidence")
        if not all(
            (review.field_semantics_correct, review.scope_correct, review.market_scope_correct)
        ):
            raise ValueError("approval cannot override semantic or scope failure")
        if review.decision == Decision.CONDITIONAL and not review.conditions:
            raise ValueError("conditional approval requires conditions")


def conservative_resolution(
    precheck_verdict: str,
    primary: PrimaryReview,
    adversarial: AdversarialReview,
    adjudication: PrimaryReview | None,
) -> Decision:
    if precheck_verdict in {
        "reject",
        "reparse_required",
        "insufficient_evidence",
        "insufficient_data",
        "requires_source_verification",
        "internal_research_only",
    }:
        return Decision.BLOCKED
    if adjudication is not None:
        if adjudication.decision in {Decision.APPROVED, Decision.CONDITIONAL} and (
            primary.decision not in {Decision.APPROVED, Decision.CONDITIONAL}
            or adversarial.recommended_decision not in {Decision.APPROVED, Decision.CONDITIONAL}
        ):
            return Decision.INCONCLUSIVE
        return adjudication.decision
    if adversarial.verdict != "agree" or primary.decision != adversarial.recommended_decision:
        return Decision.INCONCLUSIVE
    return primary.decision
