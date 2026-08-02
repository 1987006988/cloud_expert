from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from cloud_expert.database.enums import DecisionOutputLevel, DimensionScoreStatus
from cloud_expert.database.models.decision import CandidateDecisionResult, DimensionScore
from cloud_expert.decision.config import PolicyConfig
from cloud_expert.decision.rule_registry import get_score_function


def _base_policy_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "code": "test_policy",
        "version": "v1",
        "scenario_type": "compute_general",
        "effective_from": "2026-08-02T00:00:00+00:00",
        "status": "active",
        "dimensions": [
            "technical_fit",
            "availability_fit",
            "regional_fit",
            "compliance_fit",
            "reliability_fit",
            "operability_fit",
            "migration_fit",
            "cost_fit",
            "evidence_quality",
            "data_freshness",
            "review_readiness",
        ],
        "weights": {
            "technical_fit": Decimal("0.2000"),
            "availability_fit": Decimal("0.1200"),
            "regional_fit": Decimal("0.1000"),
            "compliance_fit": Decimal("0.0800"),
            "reliability_fit": Decimal("0.1000"),
            "operability_fit": Decimal("0.0800"),
            "migration_fit": Decimal("0.0800"),
            "cost_fit": Decimal("0.1400"),
            "evidence_quality": Decimal("0.0400"),
            "data_freshness": Decimal("0.0300"),
            "review_readiness": Decimal("0.0300"),
        },
        "hard_blocks": ["market_mode_mismatch"],
        "missing_data_policy": {"mandatory": "requires_review"},
        "confidence_policy": {"minimum_for_ranking": Decimal("0.6500")},
        "thresholds": {"minimum_business_fit": Decimal("0.6500")},
        "review_requirement": {"default_review_status": "machine_generated"},
        "rules": [],
    }


def test_policy_rejects_provider_bias_keys() -> None:
    payload = _base_policy_payload()
    payload["weights"] = {
        **payload["weights"],  # type: ignore[arg-type]
        "huawei_bonus": Decimal("0.0100"),
    }

    with pytest.raises(ValidationError):
        PolicyConfig.model_validate(payload)


def test_policy_requires_weights_to_sum_to_one() -> None:
    payload = _base_policy_payload()
    weights = dict(payload["weights"])  # type: ignore[arg-type]
    weights["cost_fit"] = Decimal("0.1300")
    payload["weights"] = weights

    with pytest.raises(ValidationError):
        PolicyConfig.model_validate(payload)


def test_missing_dimension_score_is_null_not_zero() -> None:
    score = DimensionScore(
        candidate_result_id=1,
        dimension="cost_fit",
        raw_score=None,
        normalized_score=None,
        weight=Decimal("0.1400"),
        weighted_score=None,
        confidence=Decimal("0.4000"),
        completeness=Decimal("0.0000"),
        status=DimensionScoreStatus.INSUFFICIENT_EVIDENCE.value,
        explanation="Missing cost is excluded and not scored as zero.",
    )

    assert score.normalized_score is None
    assert score.weighted_score is None


def test_machine_generated_result_defaults_internal_only() -> None:
    result = CandidateDecisionResult(
        decision_run_id=1,
        mapping_candidate_id=1,
        provider_id=1,
        entity_type="product",
        entity_id=1,
        decision_status="requires_review",
        confidence_level="low",
        hard_block_count=0,
        warning_count=1,
        explanation="internal",
        review_status="machine_generated",
        output_level=DecisionOutputLevel.INTERNAL_ONLY.value,
        customer_eligible=False,
    )

    assert result.output_level == "internal_only"
    assert result.customer_eligible is False


def test_custom_registered_score_function_is_not_implicit_python_execution() -> None:
    with pytest.raises(ValueError, match="custom_registered"):
        get_score_function("custom_registered")
