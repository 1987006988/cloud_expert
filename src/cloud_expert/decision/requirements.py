"""Evidence-bound target requirements; category mappings prove no SKU capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.canonical import NormalizedSpecification
from cloud_expert.database.models.decision import DecisionScenario, ScenarioRequirement
from cloud_expert.database.models.mapping import MappingCandidate
from cloud_expert.database.models.product import SKU
from cloud_expert.database.models.tco import CostLineItem, TCOResult
from cloud_expert.evidence_packages.references import freshness_for
from cloud_expert.model_review.pilot import OFFICIAL_HOSTS
from cloud_expert.normalization.evidence_validity import (
    HashCache,
    current_normalized_statement,
    normalized_evidence_valid,
)

FIELD_CODES = {
    "architecture": "compute.cpu.architecture",
    "cpu_architecture": "compute.cpu.architecture",
    "vcpu": "compute.cpu.vcpu_count",
    "memory_gib": "compute.memory.capacity_gib",
}
REQUIREMENT_DIMENSIONS = {
    "operations": "operability_fit",
    "evidence": "evidence_quality",
    "review": "review_readiness",
}


@dataclass(frozen=True)
class RequirementOutcome:
    code: str
    requirement_id: int | None
    dimension: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    evidence_ids: tuple[int, ...]
    status: str
    hard_block: bool
    requires_review: bool
    reason: str | None


def compare_value(observed: Any, expected: Any, operator: str) -> bool | None:
    if observed is None or expected is None:
        return None
    if operator in {"equals", "supports", "same_country", "same_geography"}:
        if (
            isinstance(observed, (int, float, Decimal))
            and not isinstance(observed, bool)
            and isinstance(expected, (int, float, Decimal))
            and not isinstance(expected, bool)
        ):
            return Decimal(str(observed)) == Decimal(str(expected))
        return type(observed) is type(expected) and observed == expected
    if operator in {"not_equals", "does_not_support"}:
        same = compare_value(observed, expected, "equals")
        return not same
    if operator in {"in", "not_in"}:
        if not isinstance(expected, list):
            return None
        found = any(compare_value(observed, item, "equals") for item in expected)
        return found if operator == "in" else not found
    if operator == "contains":
        return expected in observed if isinstance(observed, (list, str)) else None
    try:
        if isinstance(observed, bool) or isinstance(expected, bool):
            return None
        value = Decimal(str(observed))
        if not value.is_finite():
            return None
        if operator == "between":
            if not isinstance(expected, list) or len(expected) != 2:
                return None
            low, high = (Decimal(str(item)) for item in expected)
            return low.is_finite() and high.is_finite() and low <= value <= high
        bound = Decimal(str(expected))
        if not bound.is_finite():
            return None
        return {
            "greater_than": value > bound,
            "greater_than_or_equal": value >= bound,
            "less_than": value < bound,
            "less_than_or_equal": value <= bound,
            "evidence_at_least": value >= bound,
        }.get(operator)
    except (InvalidOperation, TypeError, ValueError):
        return None


def evaluate_requirement(
    requirement: ScenarioRequirement, observed: dict[str, Any], evidence_ids: tuple[int, ...]
) -> RequirementOutcome:
    expected = requirement.required_value or {}
    checks = [
        compare_value(observed.get(key), value, requirement.operator)
        for key, value in expected.items()
    ]
    missing = not checks or not evidence_ids or any(value is None for value in checks)
    failed = any(value is False for value in checks)
    mandatory = requirement.is_mandatory or requirement.priority in {"mandatory", "critical"}
    hard_block = bool(
        mandatory and (failed or (missing and requirement.missing_data_policy == "block"))
    )
    review = bool(missing and (mandatory or requirement.missing_data_policy == "requires_review"))
    status = "missing_data" if missing else "fail" if failed else "pass"
    return RequirementOutcome(
        requirement.requirement_code,
        requirement.id,
        REQUIREMENT_DIMENSIONS.get(
            requirement.requirement_type, f"{requirement.requirement_type}_fit"
        ),
        expected,
        observed,
        evidence_ids,
        status,
        hard_block,
        review,
        f"{requirement.requirement_code}:{status}" if status != "pass" else None,
    )


def _valid_value(
    session: Session, value: NormalizedSpecification, *, hash_cache: HashCache | None = None
) -> bool:
    if not normalized_evidence_valid(session, value, hash_cache=hash_cache):
        return False
    evidence = value.evidence
    source = evidence.source_document
    url = urlsplit(source.url)
    host = url.hostname or ""
    return (
        value.value_qualifier == "exact"
        and source.authority_level in {"official_primary", "official_secondary"}
        and source.provider_id == value.product.provider_id
        and url.scheme == "https"
        and any(host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_HOSTS)
        and freshness_for(source, datetime.now(UTC)) in {"fresh", "due_soon"}
    )


def _sku_values(
    session: Session, candidate: MappingCandidate, tco: TCOResult | None
) -> list[NormalizedSpecification]:
    sku_id = candidate.target_entity_id if candidate.target_entity_type == "sku" else None
    if sku_id is None and tco is not None:
        code = tco.scenario.workload_profile.get("compute_sku_code")
        if code:
            sku_id = session.scalar(
                select(SKU.id).where(
                    SKU.product_id == tco.product_id, SKU.provider_sku_code == code
                )
            )
    if sku_id is None:
        return []
    values = session.scalars(
        current_normalized_statement().where(NormalizedSpecification.sku_id == sku_id)
    ).all()
    hash_cache: HashCache = {}
    return [
        value
        for value in values
        if value.scope_type == "sku"
        and value.sku is not None
        and value.product.provider_id == candidate.target_provider_id
        and value.scope_identity == value.sku.provider_sku_code
        and _valid_value(session, value, hash_cache=hash_cache)
    ]


def evaluate_scenario_requirements(
    session: Session, scenario: DecisionScenario, candidate: MappingCandidate, tco: TCOResult | None
) -> list[RequirementOutcome]:
    requirements = list(scenario.requirements)
    declared = {
        (requirement.requirement_type, key)
        for requirement in requirements
        for key in (requirement.required_value or {})
    }
    # Governance flags are checked by output/review gates, not cloud capability evidence.
    for kind, values in (
        ("technical", scenario.technical_requirements),
        ("availability", scenario.availability_requirements),
        (
            "compliance",
            {
                k: v
                for k, v in (scenario.compliance_requirements or {}).items()
                if k != "customer_output_required"
            },
        ),
        ("regional", scenario.data_residency_requirements),
        (
            "operations",
            {
                k: v
                for k, v in (scenario.operational_requirements or {}).items()
                if k != "public_evidence_only"
            },
        ),
        ("migration", scenario.migration_requirements),
        (
            "reliability",
            {
                key: value
                for key, value in (scenario.workload_profile or {}).items()
                if key == "minimum_sla"
            },
        ),
    ):
        for key, value in (values or {}).items():
            if (kind, key) in declared or (
                key == "cpu_architecture" and (kind, "architecture") in declared
            ):
                continue
            requirements.append(
                ScenarioRequirement(
                    requirement_code=f"implicit_{kind}_{key}",
                    requirement_type=kind,
                    required_value={key: value},
                    operator="equals",
                    priority="mandatory",
                    is_mandatory=True,
                    missing_data_policy="requires_review",
                )
            )
            declared.add((kind, key))
    normalized_values = _sku_values(session, candidate, tco)
    lines = (
        list(
            session.scalars(
                select(CostLineItem).where(
                    CostLineItem.run_id == tco.run_id,
                    CostLineItem.product_id == tco.product_id,
                    CostLineItem.provider_id == tco.provider_id,
                )
            )
        )
        if tco is not None
        else []
    )
    outcomes = []
    for requirement in requirements:
        observed: dict[str, Any] = {}
        evidence_ids: set[int] = set()
        for key in requirement.required_value or {}:
            if key == "completeness_status" and tco is not None:
                observed[key] = tco.completeness_status
                evidence_ids.update(
                    line.evidence_id for line in lines if line.evidence_id is not None
                )
                continue
            code = FIELD_CODES.get(key)
            matches = [
                value
                for value in normalized_values
                if value.canonical_field.code == code
                and (not requirement.unit or requirement.unit == value.canonical_unit)
                and (not requirement.scope or requirement.scope == value.scope_type)
                and (not requirement.qualifier or requirement.qualifier == value.value_qualifier)
            ]
            distinct = {value.canonical_value for value in matches}
            if matches and len(distinct) == 1:
                value = matches[0]
                observed[key] = (
                    value.text_value
                    if value.text_value is not None
                    else value.numeric_value
                    if value.numeric_value is not None
                    else value.boolean_value
                )
                evidence_ids.update(item.evidence_id for item in matches)
        outcomes.append(evaluate_requirement(requirement, observed, tuple(sorted(evidence_ids))))
    return outcomes
