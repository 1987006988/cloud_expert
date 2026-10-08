"""Executable conditions for a freshly rebuilt, internal bounded-cost packet.

This contract does not replace live source, tariff, policy or freshness checks.
Callers must rebuild the packet from the database before accepting a receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from cloud_expert.pricing.scoped_tco import CORE_DIMENSIONS, RULE_VERSION

REGISTRY_VERSION = "decision_conditions.v1"
REVIEW_SCOPE = "internal_bounded_cost_only"
CONDITION_TEXT = {
    "BOUND_CONFIG": (
        "Use only the exact selected configuration and scenario-to-TCO binding in this packet; "
        "recompute and re-review after any configuration or usage change. The selected configuration "
        "does not establish customer requirements or suitability."
    ),
    "ZERO_POLICY_SCOPE": (
        "Apply each policy-zero outcome only to its evidenced policy, dimension and exact "
        "configuration context in this packet; it is not a tariff or an unconditional free service."
    ),
    "DECLARED_EXCLUSIONS": (
        "Retain every disclosed undeployed-component exclusion in this packet; enabling any "
        "excluded component requires new cost evidence, recomputation and review. Missing prices "
        "must never be treated as zero."
    ),
    "INTERNAL_CATEGORY_ONLY": (
        "Use this result only for internal single-provider bounded-cost research with "
        "product-category mapping; do not issue customer quotes, rank providers or assert SKU, "
        "architecture, performance, SLA, availability or price equivalence or advantage."
    ),
}


def _require(value: object, code: str) -> None:
    if not value:
        raise ValueError("condition_registry_" + code)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False).encode()
    ).hexdigest()


def _object(value: Any) -> dict[str, Any]:
    _require(isinstance(value, dict), "object_missing")
    assert isinstance(value, dict)
    return value


def _items(value: Any) -> list[Any]:
    _require(isinstance(value, list), "list_missing")
    assert isinstance(value, list)
    return value


def _id(value: Any) -> int:
    _require(type(value) is int and value > 0, "id_invalid")
    assert isinstance(value, int)
    return value


def _digest(value: Any) -> str:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "digest_invalid")
    assert isinstance(value, str)
    return value


def _zero(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return Decimal(str(value)).is_finite() and Decimal(str(value)) == 0
    except InvalidOperation:
        return False


def _binding(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    subject, scenario, tco = (_object(payload.get(k)) for k in ("subject", "scenario", "tco"))
    pricing = _object(tco.get("scenario"))
    workload = _object(pricing.get("workload_profile"))
    config = _object(workload.get("scoped_ecs_config"))
    context = _object(config.get("context"))
    bounded = _object(tco.get("bounded_cost_review"))
    binding = _object(payload.get("scenario_binding"))
    digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    validated = _object(binding.get("validated_configuration"))
    _require(
        config.get("purpose") == "internal_bounded_ecs_cost_research"
        and digest == workload.get("config_sha256") == bounded.get("config_sha256")
        and digest == validated.get("sha256")
        and context == bounded.get("context")
        and tco.get("rule_version") == bounded.get("validation_rule_version") == RULE_VERSION
        and validated.get("validation_rule_version") == RULE_VERSION
        and validated.get("scope") == "selected_internal_bounded_configuration_not_suitability"
        and validated.get("validation")
        == "current_prices_policies_exclusions_and_stored_tco_reconstructed",
        "config_binding_invalid",
    )
    _require(
        bounded.get("review_scope") == REVIEW_SCOPE
        and bounded.get("cross_provider_comparison_allowed") is False
        and bounded.get("comparative_advantage_allowed") is False
        and tco.get("comparability_status") == bounded.get("comparability_status") == "needs_review"
        and tco.get("completeness_status") == "complete"
        and tco.get("freshness_status") == "fresh"
        and binding.get("tco_state")
        == {k: tco[k] for k in ("completeness_status", "freshness_status", "comparability_status")}
        and subject.get("entity_type") == "product"
        and subject.get("provider_id") == tco.get("provider_id") == context.get("provider_id")
        and subject.get("entity_id") == tco.get("product_id") == context.get("product_id")
        and scenario.get("market_mode")
        == pricing.get("market_mode")
        == context.get("market_mode")
        == "domestic"
        and scenario.get("country_code") == context.get("country_code") == "CN"
        and tco.get("currency")
        == pricing.get("target_currency")
        == context.get("currency")
        == "CNY",
        "scope_invalid",
    )
    identities = {
        "CandidateDecisionResult": _id(subject.get("id")),
        "DecisionRun": _id(subject.get("decision_run_id")),
        "DecisionScenario": _id(scenario.get("id")),
        "TCOResult": _id(tco.get("id")),
        "CostCalculationRun": _id(tco.get("run_id")),
        "PricingScenario": _id(pricing.get("id")),
    }
    _require(
        _id(payload.get("target_id")) == subject["id"]
        and subject.get("tco_result_id") == tco["id"]
        and tco.get("scenario_id") == pricing["id"]
        and binding.get("schema_version") == "decision_tco_binding.v1"
        and binding.get("matching_function_result") is True,
        "subject_binding_invalid",
    )
    expected = []
    for source, key, target in (
        ("CandidateDecisionResult", "decision_run_id", "DecisionRun"),
        ("DecisionRun", "scenario_id", "DecisionScenario"),
        ("CandidateDecisionResult", "tco_result_id", "TCOResult"),
        ("TCOResult", "run_id", "CostCalculationRun"),
        ("TCOResult", "scenario_id", "PricingScenario"),
        ("CostCalculationRun", "scenario_id", "PricingScenario"),
    ):
        expected.append(
            {
                "from": {"namespace": source, "id": identities[source]},
                "to": {"namespace": target, "id": identities[target]},
                "foreign_key": key,
                "observed_fk": identities[target],
                "status": "matched",
            }
        )
    _require(
        _hash(binding.get("foreign_key_chain")) == _hash(expected), "foreign_key_proof_invalid"
    )
    for name, obj, namespace in (
        ("decision_scenario", scenario, "DecisionScenario"),
        ("pricing_scenario", pricing, "PricingScenario"),
    ):
        _require(
            bool(obj.get("scenario_version"))
            and binding.get(name)
            == {
                "namespace": namespace,
                "id": obj["id"],
                "scenario_version": obj["scenario_version"],
            },
            "scenario_version_invalid",
        )
    constraints = _items(binding.get("constraints"))
    _require(bool(constraints), "constraint_proof_missing")
    for item in constraints:
        item = _object(item)
        required, observed = item.get("required_value"), item.get("observed_value")
        operator = item.get("operator")
        _require(operator in {"equals", "python_str_equals", "member_of"}, "operator_invalid")
        if item.get("applied") is False:
            _require(
                item.get("status") == "not_specified_not_assumed" and not required,
                "unspecified_constraint_invalid",
            )
        else:
            matched = (
                str(required) == str(observed)
                if operator == "python_str_equals"
                else isinstance(required, list) and observed in required
                if operator == "member_of"
                else type(required) is type(observed) and required == observed
            )
            _require(
                item.get("applied") is True and item.get("status") == "matched" and matched,
                "constraint_mismatch",
            )
    _require(
        binding.get("contexts")
        == [
            {
                "path": "PricingScenario.workload_profile.scoped_ecs_config.context",
                "values": context,
            }
        ],
        "context_proof_invalid",
    )
    return config, bounded


def build_condition_registry(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build canonical choices and mandatory predicates without mutating the packet."""
    _require(
        payload.get("review_scope") == REVIEW_SCOPE
        and payload.get("precheck") == "passed"
        and payload.get("target_type") == "candidate_decision_result",
        "packet_scope_invalid",
    )
    config, bounded = _binding(payload)
    mapping = _object(payload.get("mapping"))
    approval = _object(mapping.get("approval"))
    _require(
        mapping.get("id") == payload["subject"].get("mapping_candidate_id")
        and mapping.get("mapping_level") == "product"
        and mapping.get("relationship_type") == "same_service_class"
        and approval.get("approved_scope") == "product_category_only"
        and approval.get("conditions_enforced") is True
        and approval.get("review_state") in {"model_approved", "model_approved_with_conditions"},
        "category_mapping_invalid",
    )
    evidence = {_id(_object(e).get("evidence_id")): e for e in _items(payload.get("evidence"))}
    _require(len(evidence) == len(payload["evidence"]) and bool(evidence), "evidence_invalid")
    costs = {_object(c).get("dimension"): c for c in _items(config.get("costs"))}
    _require(len(costs) == len(config["costs"]), "duplicate_cost_dimension")
    enabled = _items(config.get("enabled_optional_costs"))
    lines = _items(payload["tco"].get("lines"))
    zero_lines, excluded = [], []
    for line in lines:
        line = _object(line)
        assumptions = _object(line.get("assumptions") or {})
        treatment, dimension = assumptions.get("treatment"), line.get("dimension")
        if treatment not in {"policy_zero", "not_applicable"}:
            continue
        _require(
            _zero(line.get("amount"))
            and line.get("price_snapshot") is None
            and line.get("price_sku") is None
            and assumptions.get("customer_eligible") is False
            and assumptions.get("missing_prices_are_not_zero") is True
            and bool(assumptions.get("rationale")),
            "nonprice_line_invalid",
        )
        if treatment == "policy_zero":
            receipt = _object(assumptions.get("policy_receipt"))
            proof = evidence.get(_id(line.get("evidence_id")), {})
            for field in ("evidence_id", "snapshot_record_id", "source_document_id"):
                _id(receipt.get(field))
            for field in ("evidence_sha256", "raw_sha256", "manifest_sha256"):
                _digest(receipt.get(field))
            for field in ("snapshot_id", "source_document_id"):
                _id(proof.get(field))
            for field in ("excerpt_sha256", "source_sha256"):
                _digest(proof.get(field))
            _require(
                receipt.get("evidence_id") == line["evidence_id"]
                and receipt.get("evidence_sha256") == proof.get("excerpt_sha256")
                and receipt.get("raw_sha256") == proof.get("source_sha256")
                and receipt.get("snapshot_record_id") == proof.get("snapshot_id")
                and receipt.get("source_document_id") == proof.get("source_document_id")
                and isinstance(receipt.get("policy_code"), str)
                and bool(receipt["policy_code"])
                and receipt.get("rule_version") == "scoped_zero_cost_policy_v1"
                and receipt.get("dimension") == receipt.get("only_dimension") == dimension
                and receipt.get("conditions") == config["context"]
                and receipt.get("currency") == line.get("currency") == config["context"]["currency"]
                and receipt.get("price_snapshot_created") is False
                and receipt.get("customer_eligible") is False
                and receipt.get("model_approved") is False
                and _zero(receipt.get("amount"))
                and _zero(line.get("unit_price")),
                "policy_zero_proof_invalid",
            )
            zero_lines.append(line)
        else:
            cost = costs.get(dimension, {})
            _require(
                dimension not in CORE_DIMENSIONS
                and dimension not in enabled
                and cost.get("treatment") == "not_applicable"
                and _zero(cost.get("quantity"))
                and _zero(line.get("usage_quantity"))
                and cost.get("rationale") == assumptions["rationale"]
                and line.get("evidence_id") is None
                and line.get("unit_price") is None,
                "exclusion_invalid",
            )
            excluded.append(
                {
                    "dimension": dimension,
                    "rationale": cost["rationale"],
                    "quantity": cost["quantity"],
                    "treatment": "not_applicable",
                    "evidence_id": None,
                    "price_snapshot_id": None,
                }
            )
    _require(
        sorted(excluded, key=lambda x: x["dimension"])
        == sorted(_items(bounded.get("disclosed_exclusions")), key=lambda x: x["dimension"])
        and {e["dimension"] for e in excluded}
        == {k for k, c in costs.items() if c.get("treatment") == "not_applicable"},
        "exclusion_disclosure_mismatch",
    )
    proofs = {
        "BOUND_CONFIG": {"scenario_binding": payload["scenario_binding"], "configuration": config},
        "ZERO_POLICY_SCOPE": {
            "lines": zero_lines,
            "evidence": [evidence[i] for i in sorted({line["evidence_id"] for line in zero_lines})],
        },
        "DECLARED_EXCLUSIONS": {"exclusions": excluded, "enabled_optional_costs": enabled},
        "INTERNAL_CATEGORY_ONLY": {
            "mapping": mapping,
            "bounded_cost_review": bounded,
            "limitations": payload.get("limitations"),
        },
    }
    refs = {
        "BOUND_CONFIG": ["scenario_binding", "tco.scenario.workload_profile.scoped_ecs_config"],
        "ZERO_POLICY_SCOPE": ["tco.lines[*].assumptions.policy_receipt", "evidence"],
        "DECLARED_EXCLUSIONS": ["tco.bounded_cost_review.disclosed_exclusions", "tco.lines"],
        "INTERNAL_CATEGORY_ONLY": ["mapping.approval", "tco.bounded_cost_review", "limitations"],
    }
    entries = []
    for key, text in CONDITION_TEXT.items():
        if key == "ZERO_POLICY_SCOPE" and not zero_lines:
            continue
        if key == "DECLARED_EXCLUSIONS" and not excluded:
            continue
        entries.append(
            {
                "id": key,
                "version": 1,
                "text": text,
                "predicate_id": key.lower() + ".v1",
                "parameters": {
                    "target_id": payload["target_id"],
                    "config_sha256": bounded["config_sha256"],
                },
                "proof_refs": refs[key],
                "proof_sha256": _hash(proofs[key]),
            }
        )
    # Bind all review facts, not a mutable final fingerprint or the registry itself.
    facts = {
        k: v for k, v in payload.items() if k not in {"condition_registry", "input_fingerprint"}
    }
    return {
        "version": REGISTRY_VERSION,
        "review_scope": REVIEW_SCOPE,
        "binding_sha256": _hash(facts),
        "mandatory_boundaries": list(CONDITION_TEXT),
        "conditions": entries,
    }


def validate_condition_selection(
    payload: Mapping[str, Any], conditions: list[str], *, approving: bool
) -> dict[str, Any]:
    """Unknown conditions survive negative reviews but can never authorize writeback."""
    _require(
        type(approving) is bool
        and isinstance(conditions, list)
        and all(type(c) is str for c in conditions),
        "selection_invalid",
    )
    registry = build_condition_registry(payload)
    _require(_hash(payload.get("condition_registry")) == _hash(registry), "mismatch")
    allowed = {c["text"]: c["id"] for c in registry["conditions"]}
    unknown = [c for c in conditions if c not in allowed]
    if approving and unknown:
        raise ValueError("unenforceable_conditions")
    return {
        "registry_version": REGISTRY_VERSION,
        "registry_sha256": _hash(registry),
        "selected_condition_ids": sorted({allowed[c] for c in conditions if c in allowed}),
        "unknown_conditions": unknown,
    }
