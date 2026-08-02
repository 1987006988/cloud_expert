from __future__ import annotations

from pathlib import Path
from typing import Any

from cloud_expert.database.enums import ScoringDimension
from cloud_expert.decision.config import load_policy_config, load_scenario_config
from cloud_expert.decision.rule_registry import get_score_function

CONFIG_ROOT = Path("config") / "decision"


def validate_policy_file(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        policy = load_policy_config(path)
        for rule in policy.rules:
            get_score_function(rule.score_function.value)
        configured_dimensions = {dimension.value for dimension in policy.dimensions}
        missing_required_dimensions = set(ScoringDimension.values()).difference(
            configured_dimensions
        )
    except Exception as exc:
        return {"path": str(path), "valid": False, "errors": [str(exc)]}
    return {
        "path": str(path),
        "code": policy.code,
        "version": policy.version,
        "dimensions": sorted(configured_dimensions),
        "missing_optional_dimensions": sorted(missing_required_dimensions),
        "rules": len(policy.rules),
        "valid": not errors,
        "errors": errors,
    }


def validate_scenario_file(path: Path) -> dict[str, Any]:
    try:
        scenario = load_scenario_config(path)
    except Exception as exc:
        return {"path": str(path), "valid": False, "errors": [str(exc)]}
    mandatory = sum(1 for requirement in scenario.requirements if requirement.is_mandatory)
    return {
        "path": str(path),
        "code": scenario.code,
        "version": scenario.version,
        "scenario_type": scenario.scenario_type.value,
        "requirements": len(scenario.requirements),
        "mandatory_requirements": mandatory,
        "valid": True,
        "errors": [],
    }


def validate_policy_directory(root: Path = CONFIG_ROOT / "policies") -> dict[str, Any]:
    files = sorted(root.glob("*.yaml"))
    results = [validate_policy_file(path) for path in files]
    return {
        "policy_files": len(files),
        "valid_files": sum(1 for result in results if result["valid"]),
        "invalid_files": sum(1 for result in results if not result["valid"]),
        "results": results,
        "valid": bool(files) and all(result["valid"] for result in results),
    }


def validate_scenario_directory(root: Path = CONFIG_ROOT / "scenarios") -> dict[str, Any]:
    files = sorted(root.glob("*.yaml"))
    results = [validate_scenario_file(path) for path in files]
    return {
        "scenario_files": len(files),
        "valid_files": sum(1 for result in results if result["valid"]),
        "invalid_files": sum(1 for result in results if not result["valid"]),
        "results": results,
        "valid": bool(files) and all(result["valid"] for result in results),
    }
