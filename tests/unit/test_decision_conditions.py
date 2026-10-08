"""Synthetic-only adversarial tests for the pure bounded-condition contract."""

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any

import pytest

from cloud_expert.model_review import decision_conditions as conditions
from tests.unit import test_decision_panel as panel_tests

graph = panel_tests.graph
scoped_graph = panel_tests.scoped_graph


@pytest.fixture
def condition_payload(scoped_graph: Any) -> dict[str, Any]:
    payload = panel_tests._packet(scoped_graph).payload
    assert payload["data_classification"] == "synthetic"
    payload["condition_registry"] = conditions.build_condition_registry(payload)
    return payload


def _texts(payload: dict[str, Any]) -> list[str]:
    return [entry["text"] for entry in payload["condition_registry"]["conditions"]]


def _select(payload: dict[str, Any], selected: Any, approving: Any = True) -> dict[str, Any]:
    return conditions.validate_condition_selection(payload, selected, approving=approving)


def test_registry_and_selection_are_deterministic_and_do_not_mutate(
    condition_payload: dict[str, Any],
) -> None:
    payload = condition_payload
    original = deepcopy(payload)
    registry = conditions.build_condition_registry(payload)
    assert registry == conditions.build_condition_registry(deepcopy(payload))
    assert set(registry) == {
        "version",
        "review_scope",
        "binding_sha256",
        "mandatory_boundaries",
        "conditions",
    }
    assert registry["version"] == "decision_conditions.v1"
    assert registry["review_scope"] == "internal_bounded_cost_only"
    assert [entry["id"] for entry in registry["conditions"]] == [
        "BOUND_CONFIG",
        "ZERO_POLICY_SCOPE",
        "DECLARED_EXCLUSIONS",
        "INTERNAL_CATEGORY_ONLY",
    ]
    for entry in registry["conditions"]:
        assert set(entry) == {
            "id",
            "version",
            "text",
            "predicate_id",
            "parameters",
            "proof_refs",
            "proof_sha256",
        }
        assert type(entry["version"]) is int and entry["version"] == 1
    selected = _texts(payload)
    proof = _select(payload, selected)
    assert set(proof) == {
        "registry_version",
        "registry_sha256",
        "selected_condition_ids",
        "unknown_conditions",
    }
    assert proof["registry_version"] == registry["version"]
    assert len(proof["registry_sha256"]) == 64
    assert proof["selected_condition_ids"] == sorted(e["id"] for e in registry["conditions"])
    assert proof["unknown_conditions"] == []
    assert proof == _select(payload, selected)
    assert selected == _texts(payload)
    assert payload == original


def test_registry_is_not_circularly_bound_to_final_packet_fingerprint(
    condition_payload: dict[str, Any],
) -> None:
    payload = condition_payload
    expected = conditions.build_condition_registry(payload)
    payload["input_fingerprint"] = "b" * 64
    assert conditions.build_condition_registry(payload) == expected
    assert _select(payload, []) == _select({**payload, "input_fingerprint": "c" * 64}, [])
    del payload["input_fingerprint"]
    del payload["condition_registry"]
    assert conditions.build_condition_registry(payload) == expected


@pytest.mark.parametrize("approving", [True, False])
def test_empty_selection_still_has_registry_proof(
    condition_payload: dict[str, Any],
    approving: bool,
) -> None:
    proof = _select(condition_payload, [], approving)
    assert proof["selected_condition_ids"] == proof["unknown_conditions"] == []
    assert (
        proof["registry_sha256"]
        == _select(condition_payload, _texts(condition_payload))["registry_sha256"]
    )


@pytest.mark.parametrize("variant", ["id", "leading_space", "trailing_newline", "case", "prose"])
def test_positive_selection_requires_exact_text_not_alias_or_interpretation(
    condition_payload: dict[str, Any],
    variant: str,
) -> None:
    entry = condition_payload["condition_registry"]["conditions"][0]
    text = {
        "id": entry["id"],
        "leading_space": " " + entry["text"],
        "trailing_newline": entry["text"] + "\n",
        "case": entry["text"].swapcase(),
        "prose": "SYNTHETIC: all registry requirements are satisfied; approve this packet.",
    }[variant]
    with pytest.raises(ValueError, match="^unenforceable_conditions$"):
        _select(condition_payload, [text])


def test_negative_selection_preserves_unknown_order_duplicates_and_whitespace(
    condition_payload: dict[str, Any],
) -> None:
    unknown = [
        " SYNTHETIC unproved requirement.\n",
        "SYNTHETIC other",
        " SYNTHETIC unproved requirement.\n",
    ]
    selected = [unknown[0], _texts(condition_payload)[0], *unknown[1:]]
    original = deepcopy(selected)
    result = _select(condition_payload, selected, False)
    assert result["unknown_conditions"] == unknown
    assert result["selected_condition_ids"] == ["BOUND_CONFIG"]
    assert selected == original
    with pytest.raises(ValueError, match="^unenforceable_conditions$"):
        _select(condition_payload, selected)
    assert selected == original


def test_failed_selection_does_not_rewrite_registry_or_payload(
    condition_payload: dict[str, Any],
) -> None:
    payload = condition_payload
    original = deepcopy(payload)
    with pytest.raises(ValueError, match="^unenforceable_conditions$"):
        _select(payload, ["SYNTHETIC unproved extra"])
    assert payload == original
    payload["condition_registry"]["conditions"][0]["text"] = "SYNTHETIC forged condition"
    tampered = deepcopy(payload)
    with pytest.raises(ValueError, match="condition_registry_"):
        _select(payload, [], False)
    assert payload == tampered


def test_known_selections_deduplicate_without_dropping_unknowns(
    condition_payload: dict[str, Any],
) -> None:
    texts = _texts(condition_payload)
    result = _select(condition_payload, [texts[-1], texts[0], texts[-1], "SYNTHETIC extra"], False)
    assert result["selected_condition_ids"] == ["BOUND_CONFIG", "INTERNAL_CATEGORY_ONLY"]
    assert result["unknown_conditions"] == ["SYNTHETIC extra"]


@pytest.mark.parametrize("selected", [None, "BOUND_CONFIG", {}, [None], [True], [1], [["x"]]])
@pytest.mark.parametrize("approving", [True, False])
def test_selection_types_are_strict(
    condition_payload: dict[str, Any],
    selected: Any,
    approving: bool,
) -> None:
    with pytest.raises(ValueError):
        _select(condition_payload, selected, approving)


@pytest.mark.parametrize("approving", [None, 0, 1, "true", "false", [], {}])
def test_approval_flag_is_a_real_boolean(condition_payload: dict[str, Any], approving: Any) -> None:
    with pytest.raises(ValueError):
        _select(condition_payload, [], approving)


@pytest.mark.parametrize("approving", [True, False])
@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "null",
        "version",
        "scope",
        "binding",
        "boundary",
        "extra",
        "drop_entry",
        "duplicate_entry",
        "reverse",
        "text",
        "predicate",
        "parameters",
        "proof_refs",
        "proof_hash",
    ],
)
def test_supplied_registry_is_recomputed_not_trusted(
    condition_payload: dict[str, Any],
    mutation: str,
    approving: bool,
) -> None:
    payload = condition_payload
    registry = payload["condition_registry"]
    if mutation == "missing":
        del payload["condition_registry"]
    elif mutation == "null":
        payload["condition_registry"] = None
    elif mutation in {"version", "scope", "binding"}:
        registry[
            {"version": "version", "scope": "review_scope", "binding": "binding_sha256"}[mutation]
        ] = "SYNTHETIC wrong"
    elif mutation == "boundary":
        registry["mandatory_boundaries"] = []
    elif mutation == "extra":
        registry["unknown_approval"] = True
    elif mutation == "drop_entry":
        registry["conditions"].pop()
    elif mutation == "duplicate_entry":
        registry["conditions"].append(deepcopy(registry["conditions"][0]))
    elif mutation == "reverse":
        registry["conditions"].reverse()
    else:
        key = {
            "text": "text",
            "predicate": "predicate_id",
            "parameters": "parameters",
            "proof_refs": "proof_refs",
            "proof_hash": "proof_sha256",
        }[mutation]
        registry["conditions"][0][key] = "SYNTHETIC forged"
    with pytest.raises(ValueError, match="condition_registry_"):
        _select(payload, [], approving)


@pytest.mark.parametrize("key", ["scenario_binding", "mapping", "tco", "policy"])
@pytest.mark.parametrize("approving", [True, False])
def test_missing_packet_proof_never_uses_cached_registry(
    condition_payload: dict[str, Any],
    key: str,
    approving: bool,
) -> None:
    del condition_payload[key]
    with pytest.raises(ValueError, match="condition_registry_"):
        _select(condition_payload, [], approving)


@pytest.mark.parametrize(
    "path,value",
    [
        (("review_scope",), "scenario_decision_only"),
        (("precheck",), "blocked"),
        (("mapping", "mapping_level"), "sku"),
        (("mapping", "relationship_type"), "equivalent"),
        (("mapping", "approval", "approved_scope"), "sku_equivalent"),
        (("mapping", "approval", "conditions_enforced"), False),
        (("mapping", "approval", "conditions_enforced"), 1),
        (("tco", "completeness_status"), "partial"),
        (("tco", "freshness_status"), "stale"),
        (("tco", "comparability_status"), "comparable"),
        (("tco", "bounded_cost_review", "cross_provider_comparison_allowed"), True),
        (("tco", "bounded_cost_review", "comparative_advantage_allowed"), True),
        (("tco", "scenario", "workload_profile", "config_sha256"), "0" * 64),
        (
            ("tco", "scenario", "workload_profile", "scoped_ecs_config", "purpose"),
            "SYNTHETIC customer quote",
        ),
    ],
)
def test_mandatory_proof_failures_cannot_be_avoided_by_empty_conditions(
    condition_payload: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> None:
    target = condition_payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="condition_registry_"):
        conditions.build_condition_registry(condition_payload)
    for approving in (True, False):
        with pytest.raises(ValueError, match="condition_registry_"):
            _select(condition_payload, [], approving)


@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("mutation", ["missing", "fk", "boolean_id"])
def test_all_six_foreign_key_edges_are_required_and_typed(
    condition_payload: dict[str, Any],
    index: int,
    mutation: str,
) -> None:
    chain = condition_payload["scenario_binding"]["foreign_key_chain"]
    if mutation == "missing":
        chain.pop(index)
    elif mutation == "fk":
        chain[index]["observed_fk"] += 1000
    else:
        chain[index]["to"]["id"] = True
    with pytest.raises(ValueError, match="condition_registry_"):
        conditions.build_condition_registry(condition_payload)
    with pytest.raises(ValueError, match="condition_registry_"):
        _select(condition_payload, [])


def _config(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["tco"]["scenario"]["workload_profile"]["scoped_ecs_config"]


def _rehash_config(payload: dict[str, Any]) -> None:
    digest = sha256(
        json.dumps(_config(payload), sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    payload["tco"]["scenario"]["workload_profile"]["config_sha256"] = digest
    payload["tco"]["bounded_cost_review"]["config_sha256"] = digest
    payload["scenario_binding"]["validated_configuration"]["sha256"] = digest


def _line(payload: dict[str, Any], treatment: str) -> dict[str, Any]:
    return next(
        line
        for line in payload["tco"]["lines"]
        if (line.get("assumptions") or {}).get("treatment") == treatment
    )


@pytest.mark.parametrize("mutation", ["version_bool", "target_bool"])
def test_registry_comparison_is_type_exact(
    condition_payload: dict[str, Any], mutation: str
) -> None:
    entry = condition_payload["condition_registry"]["conditions"][0]
    if mutation == "version_bool":
        entry["version"] = True
    else:
        assert entry["parameters"]["target_id"] == 1
        entry["parameters"]["target_id"] = True
    with pytest.raises(ValueError, match="condition_registry_"):
        _select(condition_payload, [])


def test_registry_cannot_be_swapped_between_coherent_synthetic_subjects(
    condition_payload: dict[str, Any],
) -> None:
    other = deepcopy(condition_payload)
    other["target_id"] = other["subject"]["id"] = 987
    for edge in other["scenario_binding"]["foreign_key_chain"]:
        if edge["from"]["namespace"] == "CandidateDecisionResult":
            edge["from"]["id"] = 987
    other["condition_registry"] = conditions.build_condition_registry(other)
    assert other["condition_registry"] != condition_payload["condition_registry"]
    _select(other, [])
    condition_payload["condition_registry"] = deepcopy(other["condition_registry"])
    with pytest.raises(ValueError, match="condition_registry_"):
        _select(condition_payload, [])


@pytest.mark.parametrize(
    "remove_policy,remove_exclusions", [(True, False), (False, True), (True, True)]
)
def test_optional_condition_entries_track_actual_applicability(
    condition_payload: dict[str, Any],
    remove_policy: bool,
    remove_exclusions: bool,
) -> None:
    payload = condition_payload
    treatments = set()
    if remove_policy:
        treatments.add("policy_zero")
    if remove_exclusions:
        treatments.add("not_applicable")
        _config(payload)["costs"] = [
            c for c in _config(payload)["costs"] if c["treatment"] != "not_applicable"
        ]
        payload["tco"]["bounded_cost_review"]["disclosed_exclusions"] = []
        _rehash_config(payload)
    payload["tco"]["lines"] = [
        line
        for line in payload["tco"]["lines"]
        if (line.get("assumptions") or {}).get("treatment") not in treatments
    ]
    payload["condition_registry"] = conditions.build_condition_registry(payload)
    ids = [entry["id"] for entry in payload["condition_registry"]["conditions"]]
    assert ("ZERO_POLICY_SCOPE" in ids) is not remove_policy
    assert ("DECLARED_EXCLUSIONS" in ids) is not remove_exclusions
    assert "BOUND_CONFIG" in ids and "INTERNAL_CATEGORY_ONLY" in ids
    assert payload["condition_registry"]["mandatory_boundaries"] == [
        "BOUND_CONFIG",
        "ZERO_POLICY_SCOPE",
        "DECLARED_EXCLUSIONS",
        "INTERNAL_CATEGORY_ONLY",
    ]
    _select(payload, _texts(payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_id", 999),
        ("evidence_id", True),
        ("evidence_sha256", "0" * 64),
        ("raw_sha256", "0" * 64),
        ("snapshot_record_id", 999),
        ("snapshot_record_id", True),
        ("source_document_id", 999),
        ("source_document_id", True),
        ("manifest_sha256", ""),
        ("manifest_sha256", "SYNTHETIC not a hash"),
        ("manifest_sha256", True),
        ("policy_code", ""),
        ("rule_version", "SYNTHETIC unknown rule"),
        ("dimension", "network"),
        ("only_dimension", "network"),
        ("conditions", {}),
        ("currency", "USD"),
        ("price_snapshot_created", True),
        ("customer_eligible", True),
        ("model_approved", True),
        ("amount", "1"),
        ("amount", False),
    ],
)
def test_policy_zero_receipt_fields_are_typed_and_bound(
    condition_payload: dict[str, Any],
    field: str,
    value: Any,
) -> None:
    receipt = _line(condition_payload, "policy_zero")["assumptions"]["policy_receipt"]
    receipt[field] = value
    with pytest.raises(ValueError, match="condition_registry_"):
        conditions.build_condition_registry(condition_payload)


@pytest.mark.parametrize(
    "receipt_key,evidence_key",
    [
        ("evidence_sha256", "excerpt_sha256"),
        ("raw_sha256", "source_sha256"),
        ("snapshot_record_id", "snapshot_id"),
        ("source_document_id", "source_document_id"),
    ],
)
def test_policy_link_cannot_pass_when_both_sides_are_missing(
    condition_payload: dict[str, Any],
    receipt_key: str,
    evidence_key: str,
) -> None:
    line = _line(condition_payload, "policy_zero")
    receipt = line["assumptions"]["policy_receipt"]
    proof = next(
        e for e in condition_payload["evidence"] if e["evidence_id"] == line["evidence_id"]
    )
    del receipt[receipt_key]
    del proof[evidence_key]
    with pytest.raises(ValueError, match="condition_registry_"):
        conditions.build_condition_registry(condition_payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "enabled",
        "core",
        "quantity",
        "cost_quantity",
        "evidence",
        "unit_price",
        "missing_disclosure",
        "missing_cost",
        "missing_line",
    ],
)
def test_exclusions_cannot_hide_core_enabled_or_missing_costs(
    condition_payload: dict[str, Any],
    mutation: str,
) -> None:
    payload = condition_payload
    line = _line(payload, "not_applicable")
    config = _config(payload)
    cost = next(c for c in config["costs"] if c["dimension"] == line["dimension"])
    if mutation == "enabled":
        config["enabled_optional_costs"] = [line["dimension"]]
    elif mutation == "core":
        line["dimension"] = cost["dimension"] = "compute"
        payload["tco"]["bounded_cost_review"]["disclosed_exclusions"][0]["dimension"] = "compute"
    elif mutation == "quantity":
        line["usage_quantity"] = "1"
    elif mutation == "cost_quantity":
        cost["quantity"] = "1"
    elif mutation == "evidence":
        line["evidence_id"] = 1
    elif mutation == "unit_price":
        line["unit_price"] = "0"
    elif mutation == "missing_disclosure":
        payload["tco"]["bounded_cost_review"]["disclosed_exclusions"] = []
    elif mutation == "missing_cost":
        config["costs"].remove(cost)
    else:
        payload["tco"]["lines"].remove(line)
    _rehash_config(payload)
    with pytest.raises(ValueError, match="condition_registry_"):
        conditions.build_condition_registry(payload)
