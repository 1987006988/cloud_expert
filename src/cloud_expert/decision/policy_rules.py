"""Execute registered policy inputs, never treating an absent input as zero."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from cloud_expert.database.enums import TCOCompletenessStatus
from cloud_expert.database.models.decision import ScoringRule
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.decision.requirements import compare_value
from cloud_expert.decision.rule_registry import get_score_function


def _normalized_number(value: Any, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return False
    try:
        number = Decimal(str(value))
        return number.is_finite() and (0 < number <= 1 if positive else 0 <= number <= 1)
    except ArithmeticError:
        return False


def _supported_inputs(rule: ScoringRule, value: Any, bound: Any) -> bool:
    conditions = rule.conditions or {}
    if not isinstance(conditions, dict) or set(conditions) != {"source"}:
        return False
    expected = rule.expected_value or {}
    if not isinstance(expected, dict):
        return False
    source = conditions["source"]
    if not isinstance(source, str):
        return False
    if rule.minimum_score != Decimal(0) or rule.maximum_score != Decimal(1):
        return False
    if source == "week9_tco_result":
        return (
            set(expected) == {"completeness_status"}
            and bound == "complete"
            and isinstance(value, str)
            and value in TCOCompletenessStatus.values()
            and rule.operator == "equals"
            and rule.score_function == "exact_match"
        )
    functions = {
        "week7_mapping_candidate": {"ratio_fit", "threshold_fit"},
        "week8_evidence_package": {"evidence_fit", "completeness_fit", "threshold_fit"},
    }
    return (
        source in functions
        and set(expected) == {"minimum"}
        and rule.operator in {"greater_than_or_equal", "evidence_at_least"}
        and rule.score_function in functions[source]
        and _normalized_number(value)
        and _normalized_number(bound, positive=True)
    )


@dataclass(frozen=True)
class PolicyOutcome:
    rule_id: int
    observed: dict[str, Any]
    expected: dict[str, Any]
    evidence_ids: tuple[int, ...]
    status: str
    score: Decimal | None
    hard_block: bool
    requires_review: bool
    reason: str | None


def evaluate_policy_rule(
    rule: ScoringRule,
    candidate: MappingCandidate,
    package: EvidencePackage | None,
    tco: TCOResult | None,
    evidence_ids: tuple[int, ...],
) -> PolicyOutcome:
    expected = rule.expected_value if isinstance(rule.expected_value, dict) else {}
    conditions = rule.conditions if isinstance(rule.conditions, dict) else {}
    source = conditions.get("source")
    value: Any = None
    bound: Any = None
    observed: dict[str, Any] = {}
    if source == "week7_mapping_candidate" and candidate.mapping_level == "sku":
        value = candidate.normalized_score
        bound = expected.get("minimum")
        observed = {"normalized_mapping_score": str(value) if value is not None else None}
    elif source == "week8_evidence_package" and package is not None:
        value = package.evidence_completeness
        bound = expected.get("minimum")
        observed = {"evidence_completeness": str(value) if value is not None else None}
    elif source == "week9_tco_result" and tco is not None:
        value = tco.completeness_status
        bound = expected.get("completeness_status")
        observed = {"completeness_status": value, "tco_result_id": tco.id}
    checked = None
    score = None
    requirements = rule.evidence_requirement or {}
    requirements_valid = (
        isinstance(requirements, dict)
        and set(requirements).issubset({"evidence_package_required", "price_snapshot_required"})
        and all(isinstance(item, bool) for item in requirements.values())
        and (not requirements.get("evidence_package_required") or package is not None)
        and (not requirements.get("price_snapshot_required") or tco is not None)
    )
    if evidence_ids and requirements_valid and _supported_inputs(rule, value, bound):
        try:
            checked = compare_value(value, bound, rule.operator)
            score = get_score_function(rule.score_function)(value, bound)
            if checked is None or not isinstance(score, Decimal) or not _normalized_number(score):
                score = None
        except (ValueError, ArithmeticError, TypeError):
            score = None
    if not evidence_ids or score is None:
        checked = None
    status = "missing_data" if checked is None else "pass" if checked else "fail"
    critical = rule.priority in {"critical", "mandatory"}
    hard_block = critical and (
        checked is False or (checked is None and rule.missing_data_policy == "block")
    )
    review = checked is None and (critical or rule.missing_data_policy == "requires_review")
    return PolicyOutcome(
        rule.id,
        observed,
        expected,
        evidence_ids,
        status,
        score,
        hard_block,
        review,
        f"{rule.rule_code}:{status}" if status != "pass" else None,
    )
