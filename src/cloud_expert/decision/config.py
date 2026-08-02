from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cloud_expert.database.enums import (
    DecisionScenarioStatus,
    DecisionScenarioType,
    MarketMode,
    MissingDataPolicy,
    ScenarioRequirementOperator,
    ScenarioRequirementPriority,
    ScenarioRequirementType,
    ScoreFunction,
    ScoringDimension,
    ScoringPolicyStatus,
)

BANNED_WEIGHT_KEYS = {
    "provider_bonus",
    "huawei_bonus",
    "aws_penalty",
    "aliyun_penalty",
    "preferred_vendor_bonus",
}


class RequirementConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    requirement_type: ScenarioRequirementType
    operator: ScenarioRequirementOperator
    required_value: dict[str, Any] | None = None
    unit: str | None = None
    qualifier: str | None = None
    scope: str | None = None
    priority: ScenarioRequirementPriority
    is_mandatory: bool = False
    missing_data_policy: MissingDataPolicy
    evidence_requirement: dict[str, Any] | None = None


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    code: str
    version: str
    name: str
    description: str | None = None
    scenario_type: DecisionScenarioType
    market_mode: MarketMode
    industry: str | None = None
    country_code: str | None = None
    preferred_regions: list[str] = Field(default_factory=list)
    workload_profile: dict[str, Any]
    technical_requirements: dict[str, Any] | None = None
    availability_requirements: dict[str, Any] | None = None
    compliance_requirements: dict[str, Any] | None = None
    data_residency_requirements: dict[str, Any] | None = None
    operational_requirements: dict[str, Any] | None = None
    migration_requirements: dict[str, Any] | None = None
    budget_preferences: dict[str, Any] | None = None
    scoring_policy_code: str
    scoring_policy_version: str
    effective_from: str
    status: DecisionScenarioStatus
    requirements: list[RequirementConfig]

    @model_validator(mode="after")
    def require_mandatory(self) -> ScenarioConfig:
        if not any(req.is_mandatory for req in self.requirements):
            raise ValueError("scenario must include at least one mandatory requirement")
        return self


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    version: str
    dimension: ScoringDimension
    operator: ScenarioRequirementOperator
    expected_value: dict[str, Any] | None = None
    minimum_score: Decimal | None = None
    maximum_score: Decimal | None = None
    score_function: ScoreFunction
    conditions: dict[str, Any] | None = None
    evidence_requirement: dict[str, Any] | None = None
    missing_data_policy: MissingDataPolicy
    priority: ScenarioRequirementPriority
    status: ScoringPolicyStatus


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    code: str
    version: str
    scenario_type: DecisionScenarioType
    description: str | None = None
    effective_from: str
    status: ScoringPolicyStatus
    dimensions: list[ScoringDimension]
    weights: dict[str, Decimal]
    hard_blocks: list[dict[str, Any] | str]
    missing_data_policy: dict[str, Any]
    confidence_policy: dict[str, Any]
    thresholds: dict[str, Any]
    review_requirement: dict[str, Any]
    rules: list[RuleConfig]

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        banned = BANNED_WEIGHT_KEYS.intersection(value)
        if banned:
            raise ValueError(f"provider bias keys are not allowed: {sorted(banned)}")
        total = sum(value.values(), Decimal("0"))
        if total != Decimal("1.0000") and total != Decimal("1"):
            raise ValueError(f"weights must sum to 1.0000, got {total}")
        for key, weight in value.items():
            if key not in ScoringDimension.values():
                raise ValueError(f"unknown scoring dimension: {key}")
            if weight < 0 or weight > 1:
                raise ValueError(f"dimension weight out of range: {key}")
        return value

    @model_validator(mode="after")
    def validate_dimensions(self) -> PolicyConfig:
        dimension_values = {dimension.value for dimension in self.dimensions}
        if dimension_values != set(self.weights):
            raise ValueError("policy dimensions must match weight keys")
        return self


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return loaded


def load_policy_config(path: Path) -> PolicyConfig:
    return PolicyConfig.model_validate(load_yaml(path))


def load_scenario_config(path: Path) -> ScenarioConfig:
    return ScenarioConfig.model_validate(load_yaml(path))
