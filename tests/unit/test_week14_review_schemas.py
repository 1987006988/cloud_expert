import pytest
from pydantic import ValidationError

from cloud_expert.model_review.schemas import (
    AdversarialReview,
    Decision,
    PrimaryReview,
    conservative_resolution,
    validate_review_evidence,
)


def _primary(decision: Decision = Decision.APPROVED) -> PrimaryReview:
    return PrimaryReview(
        decision=decision,
        confidence=0.9,
        supported_by_evidence=True,
        field_semantics_correct=True,
        scope_correct=True,
        market_scope_correct=True,
        conditions=[],
        blocking_reasons=[],
        required_repairs=[],
        evidence_references=[10],
        reasoning_summary="Synthetic fixture supports this internal candidate.",
    )


def test_strict_model_output_and_evidence_ids() -> None:
    review = _primary()
    validate_review_evidence(review, {10})
    with pytest.raises(ValueError, match="outside"):
        validate_review_evidence(review, {11})
    with pytest.raises(ValidationError):
        PrimaryReview.model_validate({**review.model_dump(), "unexpected": "claim"})
    with pytest.raises(ValidationError):
        PrimaryReview.model_validate({**review.model_dump(), "confidence": 1.1})
    with pytest.raises(ValueError, match="conditions"):
        validate_review_evidence(review.model_copy(update={"decision": Decision.CONDITIONAL}), {10})


def test_disagreement_and_deterministic_block_cannot_approve() -> None:
    adversarial = AdversarialReview(
        verdict="disagree",
        identified_errors=["Synthetic scope ambiguity"],
        missing_conditions=[],
        recommended_decision=Decision.INCONCLUSIVE,
        confidence=0.8,
        evidence_references=[10],
        reasoning_summary="Synthetic fixture is inconclusive.",
    )
    assert (
        conservative_resolution("requires_dual_model_review", _primary(), adversarial, None)
        == Decision.INCONCLUSIVE
    )
    assert (
        conservative_resolution("reject", _primary(), adversarial, _primary()) == Decision.BLOCKED
    )


def test_adjudication_can_choose_inconclusive_over_unproven_reparse() -> None:
    primary = _primary(Decision.INCONCLUSIVE)
    adversarial = AdversarialReview(
        verdict="agree",
        identified_errors=["Product-level evidence is absent"],
        missing_conditions=[],
        recommended_decision=Decision.REPARSE,
        confidence=0.9,
        evidence_references=[10],
        reasoning_summary="A parser defect is not established.",
    )
    adjudication = _primary(Decision.INCONCLUSIVE)
    assert (
        conservative_resolution("requires_dual_model_review", primary, adversarial, adjudication)
        == Decision.INCONCLUSIVE
    )
    assert (
        conservative_resolution("requires_dual_model_review", primary, adversarial, _primary())
        == Decision.INCONCLUSIVE
    )
