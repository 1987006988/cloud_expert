"""Synthetic namespace/FK proofs and CLI integration; no business DB or model calls."""

import hashlib
import json
import subprocess
from copy import deepcopy

import pytest

from cloud_expert.database.models.tco import PricingScenario
from cloud_expert.model_review import decision_panel as panel
from cloud_expert.model_review.schemas import Decision
from tests.unit import test_decision_panel as panel_tests
from tests.unit.test_decision_panel import _cli_stub, _opinion, _packet

base_graph = panel_tests.graph
base_scoped_graph = panel_tests.scoped_graph
isolated_codex_home = panel_tests.isolated_codex_home
packet = panel_tests.packet


@pytest.fixture
def graph(base_graph):
    graph = base_graph
    graph.result.decision_run_id = graph.run.id
    graph.scenario.id = 42
    graph.run.scenario_id = graph.scenario.id
    graph.requirement.scenario_id = graph.scenario.id
    graph.pricing.id = 84
    graph.pricing.scenario_version = "synthetic-pricing-v3"
    graph.tco.scenario_id = graph.cost_run.scenario_id = graph.pricing.id
    return graph


@pytest.fixture
def scoped_graph(base_scoped_graph):
    graph = base_scoped_graph
    config = graph.pricing.workload_profile["scoped_ecs_config"]
    config["context"].update(market_mode="domestic", currency="CNY", provider_id=1, product_id=2)
    graph.pricing.workload_profile["config_sha256"] = panel.scoped_tco._hash(config)
    return graph


def _binding(graph):
    scoped = panel._scoped_cost_review(graph.session, graph.result, graph.tmp_path, graph.now)
    return panel._scenario_binding(graph.session, graph.result, scoped, [graph.line])


def _usage(proof, key):
    return next(
        item
        for item in proof["constraints"]
        if item["required_path"] == f"DecisionScenario.workload_profile.{key}"
    )


def test_distinct_namespace_ids_and_versions_are_bound_by_exact_fks(graph):
    packet = _packet(graph)
    proof = packet.payload["scenario_binding"]
    assert proof["schema_version"] == "decision_tco_binding.v1"
    assert proof["decision_scenario"] == {
        "namespace": "DecisionScenario",
        "id": 42,
        "scenario_version": "v1",
    }
    assert proof["pricing_scenario"] == {
        "namespace": "PricingScenario",
        "id": 84,
        "scenario_version": "synthetic-pricing-v3",
    }
    assert [
        (e["from"]["namespace"], e["foreign_key"], e["to"]["namespace"])
        for e in proof["foreign_key_chain"]
    ] == [
        ("CandidateDecisionResult", "decision_run_id", "DecisionRun"),
        ("DecisionRun", "scenario_id", "DecisionScenario"),
        ("CandidateDecisionResult", "tco_result_id", "TCOResult"),
        ("TCOResult", "run_id", "CostCalculationRun"),
        ("TCOResult", "scenario_id", "PricingScenario"),
        ("CostCalculationRun", "scenario_id", "PricingScenario"),
    ]
    assert all(e["observed_fk"] == e["to"]["id"] for e in proof["foreign_key_chain"])
    assert proof["matching_function_result"] is True
    assert proof["validated_configuration"] is None
    assert packet.payload["prompt_version"] == "decision-panel.v4"
    payload_without_fingerprint = packet.payload
    del payload_without_fingerprint["input_fingerprint"]
    assert json.loads(packet.manifest_json)["public_payload_sha256"] == panel._hash(
        payload_without_fingerprint
    )
    graph.session.flush.assert_not_called()
    graph.session.commit.assert_not_called()


@pytest.mark.parametrize(
    "row,field",
    [
        ("result", "decision_run_id"),
        ("run", "scenario_id"),
        ("result", "tco_result_id"),
        ("tco", "run_id"),
        ("tco", "scenario_id"),
        ("cost_run", "scenario_id"),
    ],
)
@pytest.mark.parametrize("value", [None, 999, True])
def test_broken_fk_never_becomes_binding(graph, row, field, value):
    setattr(getattr(graph, row), field, value)
    with pytest.raises(ValueError, match="scenario_binding_fk_mismatch"):
        _binding(graph)


@pytest.mark.parametrize(
    "row,field",
    [
        ("result", "decision_run"),
        ("result", "tco_result"),
        ("run", "scenario"),
        ("tco", "scenario"),
        ("tco", "run"),
        ("cost_run", "scenario"),
    ],
)
def test_missing_relationship_fails_closed(graph, row, field):
    setattr(getattr(graph, row), field, None)
    with pytest.raises(ValueError, match="scenario_binding_link_missing"):
        _binding(graph)


def test_coincident_ids_do_not_repair_wrong_subject_fk(graph):
    graph.pricing.id = graph.scenario.id
    graph.tco.scenario_id = graph.cost_run.scenario_id = graph.pricing.id
    graph.result.tco_result_id = 999
    with pytest.raises(ValueError, match="scenario_binding_fk_mismatch"):
        _binding(graph)


@pytest.mark.parametrize("row,version", [("run", "wrong"), ("scenario", ""), ("pricing", "")])
def test_stale_or_missing_version_is_not_binding(graph, row, version):
    getattr(graph, row).scenario_version = version
    with pytest.raises(ValueError, match="scenario_binding_version_or_identity_mismatch"):
        _binding(graph)


def test_same_id_but_distinct_pricing_objects_rejected(graph):
    graph.cost_run.scenario = PricingScenario(id=graph.pricing.id, scenario_version="forged")
    with pytest.raises(ValueError, match="scenario_binding_version_or_identity_mismatch"):
        _binding(graph)


def test_binding_revalidates_matcher(graph, monkeypatch):
    calls = []
    monkeypatch.setattr(panel, "_tco_matches_scenario", lambda *args: calls.append(args) or False)
    with pytest.raises(ValueError, match="tco_incomplete_or_wrong_scenario"):
        _binding(graph)
    assert calls == [(graph.session, graph.tco, graph.scenario)]


@pytest.mark.parametrize(
    "key,pricing_key",
    [
        ("storage_gb_month", "storage_gb_month"),
        ("requests_per_month", "requests_per_month"),
        ("outbound_gb", "outbound_gb"),
        ("monthly_hours", "compute_instance_hours"),
        ("vcpu", "vcpu"),
        ("memory_gb", "memory_gb"),
    ],
)
def test_exact_applied_usage_observations_and_no_numeric_conversion(scoped_graph, key, pricing_key):
    graph = scoped_graph
    graph.scenario.workload_profile[key] = 3
    graph.pricing.workload_profile[pricing_key] = "3"
    observed = _usage(_binding(graph), key)
    assert observed["required_value"] == 3 and observed["observed_value"] == "3"
    assert observed["operator"] == "python_str_equals"
    assert observed["status"] == "matched" and observed["applied"] is True
    graph.pricing.workload_profile[pricing_key] = "3.0"
    with pytest.raises(ValueError, match="scenario_binding_constraint_mismatch"):
        _binding(graph)


def test_unspecified_memory_is_not_inferred_from_gib_configuration(scoped_graph):
    graph = scoped_graph
    graph.pricing.workload_profile.update(vcpu=4, memory_value="16", memory_unit="GiB")
    graph.scenario.workload_profile.update(category="compute", purpose="synthetic_audit")
    proof = _binding(graph)
    for key in ("memory_gb", "vcpu", "storage_gb_month", "requests_per_month", "outbound_gb"):
        row = _usage(proof, key)
        assert row["required_value"] is None
        assert row["applied"] is False and row["status"] == "not_specified_not_assumed"
    assert _usage(proof, "vcpu")["observed_value"] == 4
    assert _usage(proof, "memory_gb")["observed_value"] is None
    assert proof["workload_keys_not_compared_by_usage_matcher"] == ["category", "purpose"]
    assert "not customer suitability" in proof["limitations"][0]


@pytest.mark.parametrize("key,value", [("vcpu", 0), ("memory_gb", 0), ("monthly_hours", 0)])
def test_explicit_zero_constraint_is_not_unspecified(scoped_graph, key, value):
    scoped_graph.scenario.workload_profile[key] = value
    with pytest.raises(ValueError, match="scenario_binding_constraint_mismatch"):
        _binding(scoped_graph)


@pytest.mark.parametrize(
    "key,value",
    [
        ("region", "other-region"),
        ("country_code", "US"),
        ("market_mode", "international"),
        ("currency", "USD"),
        ("provider_id", 99),
        ("product_id", 99),
    ],
)
def test_even_self_consistently_hashed_wrong_context_is_rejected(scoped_graph, key, value):
    config = scoped_graph.pricing.workload_profile["scoped_ecs_config"]
    config["context"][key] = value
    scoped_graph.pricing.workload_profile["config_sha256"] = panel.scoped_tco._hash(config)
    with pytest.raises(ValueError, match="scenario_binding_constraint_mismatch"):
        _binding(scoped_graph)


@pytest.mark.parametrize(
    "row,field,value",
    [
        ("result", "provider_id", 99),
        ("result", "entity_id", 99),
        ("pricing", "market_mode", "international"),
        ("pricing", "target_currency", "USD"),
        ("scenario", "budget_preferences", {"currency": "USD"}),
    ],
)
def test_wrong_target_or_currency_fails_closed(scoped_graph, row, field, value):
    setattr(getattr(scoped_graph, row), field, value)
    with pytest.raises(ValueError, match="scenario_binding_constraint_mismatch"):
        _binding(scoped_graph)


@pytest.mark.parametrize("mutation", ["hash", "config", "receipt", "rule"])
def test_config_tamper_fails_closed(scoped_graph, mutation):
    graph = scoped_graph
    scoped = panel._scoped_cost_review(graph.session, graph.result, graph.tmp_path, graph.now)
    if mutation == "hash":
        graph.pricing.workload_profile["config_sha256"] = "0" * 64
    elif mutation == "config":
        graph.pricing.workload_profile["scoped_ecs_config"]["unexpected"] = "changed"
    elif mutation == "receipt":
        scoped["config_sha256"] = "0" * 64
    else:
        scoped["validation_rule_version"] = "old"
    with pytest.raises(ValueError, match="scenario_binding_config_hash_mismatch"):
        panel._scenario_binding(graph.session, graph.result, scoped, [graph.line])


def test_config_requires_successful_reconstruction(scoped_graph):
    graph = scoped_graph
    graph.validator.return_value = False
    with pytest.raises(ValueError, match="scoped_tco_validation_failed"):
        _packet(graph)
    with pytest.raises(ValueError, match="scenario_binding_config_not_validated"):
        panel._scenario_binding(graph.session, graph.result, None, [graph.line])


def test_subject_and_configuration_changes_rebind_packet_fingerprint(scoped_graph):
    graph = scoped_graph
    first = _packet(graph)
    graph.run.id = graph.result.decision_run_id = 987
    second = _packet(graph)
    assert second.fingerprint != first.fingerprint
    config = graph.pricing.workload_profile["scoped_ecs_config"]
    config["context"]["support_plan"] = "synthetic-basic"
    digest = graph.pricing.workload_profile["config_sha256"] = panel.scoped_tco._hash(config)
    third = _packet(graph)
    assert third.fingerprint != second.fingerprint
    assert third.payload["scenario_binding"]["validated_configuration"]["sha256"] == digest
    assert third.payload["tco"]["bounded_cost_review"]["config_sha256"] == digest


@pytest.mark.parametrize(
    "key,value", [("account_id", "private"), ("secret", "private"), ("note", "personal_discounts")]
)
def test_binding_does_not_bypass_privacy(scoped_graph, key, value):
    config = scoped_graph.pricing.workload_profile["scoped_ecs_config"]
    config["context"][key] = value
    scoped_graph.pricing.workload_profile["config_sha256"] = panel.scoped_tco._hash(config)
    with pytest.raises(ValueError, match="sensitive_content_rejected"):
        _binding(scoped_graph)


def test_no_local_narratives_or_paths_enter_binding(graph):
    graph.result.explanation = "private local reasoning"
    graph.scenario.name = "private local title"
    encoded = panel._json(_binding(graph))
    assert "private local" not in encoded
    assert str(graph.tmp_path) not in encoded
    assert "storage_path" not in encoded


def test_v4_prompt_and_schema_explain_binding_without_predetermined_approval(packet):
    prompt = panel._prompt("primary", packet, [])
    assert "distinct model namespaces" in prompt
    assert "not an instruction to approve" in prompt
    assert "Unspecified requirements must remain unspecified" in prompt
    description = panel.Checks.model_json_schema()["properties"]["exact_tco_scenario"][
        "description"
    ]
    assert "separate namespaces" in description
    assert "equal IDs are not proof" in description
    primary = panel.DecisionOpinion.model_validate(
        _opinion(packet, decision=Decision.BLOCKED, conditions=["Exact original condition."])
    )
    prompt = panel._prompt("arbitration", packet, [primary, primary])
    assert "Preserve ALL original primary and adversarial condition strings exactly" in prompt
    assert "regardless of the final decision" in prompt
    assert "Exact original condition." in prompt


@pytest.mark.parametrize("decision", list(Decision))
@pytest.mark.parametrize("conditions", [[], ["Use BASIC support."], ["Use basic support. "]])
def test_arbitration_cannot_drop_or_paraphrase_conditions_for_any_outcome(
    packet, decision, conditions
):
    primary = panel.DecisionOpinion.model_validate(
        _opinion(packet, decision=Decision.CONDITIONAL, conditions=["Use basic support."])
    )
    adversarial = panel.DecisionOpinion.model_validate(
        _opinion(
            packet,
            stage="adversarial",
            decision=Decision.CONDITIONAL,
            conditions=["Retain all exclusions."],
        )
    )
    arbitration = panel.DecisionOpinion.model_validate(
        _opinion(packet, stage="arbitration", decision=decision, conditions=conditions)
    )
    assert panel.resolve_panel_opinions(primary, adversarial, arbitration) == Decision.INCONCLUSIVE


@pytest.mark.parametrize("decision", list(Decision))
def test_arbitration_may_add_but_preserves_exact_original_strings(packet, decision):
    conditions = ["Use basic support.", "Retain all exclusions."]
    primary = panel.DecisionOpinion.model_validate(
        _opinion(packet, decision=Decision.CONDITIONAL, conditions=conditions[:1])
    )
    adversarial = panel.DecisionOpinion.model_validate(
        _opinion(
            packet, stage="adversarial", decision=Decision.CONDITIONAL, conditions=conditions[1:]
        )
    )
    arbitration = panel.DecisionOpinion.model_validate(
        _opinion(
            packet,
            stage="arbitration",
            decision=decision,
            conditions=[*conditions, "Additional restriction."],
        )
    )
    assert panel.resolve_panel_opinions(primary, adversarial, arbitration) == decision


STARTUP_NOTICE = {
    "type": "item.completed",
    "item": {
        "id": "item_0",
        "type": "error",
        "message": "Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.",
    },
}


@pytest.mark.parametrize(
    "mutation", [None, "text", "position", "duplicate", "tool", "two_final_messages", "wrong_model"]
)
def test_cli_helper_integration_preserves_raw_stream_and_fails_closed(
    packet, tmp_path, monkeypatch, mutation
):
    _cli_stub(monkeypatch, packet)
    execute = panel.subprocess.run
    captured = []

    def with_notice(*args, **kwargs):
        completed = execute(*args, **kwargs)
        events = [json.loads(line) for line in completed.stdout.splitlines()]
        events[2]["item"]["id"] = "item_1"
        notice = deepcopy(STARTUP_NOTICE)
        if mutation == "text":
            notice["item"]["message"] += " altered"
        if mutation == "tool":
            notice["item"]["type"] = "command_execution"
        events.insert(2 if mutation == "position" else 1, notice)
        if mutation == "duplicate":
            events.insert(2, deepcopy(notice))
        if mutation == "two_final_messages":
            events.insert(-1, deepcopy(events[-2]))
        if mutation == "wrong_model":
            events[2]["model"] = "other"
        raw = b"\r\n".join(json.dumps(event).encode() for event in events) + b"\r\n"
        captured.append(raw)
        return subprocess.CompletedProcess(completed.args, 0, raw, completed.stderr)

    monkeypatch.setattr(panel.subprocess, "run", with_notice)
    if mutation:
        with pytest.raises(RuntimeError, match="model_stage_failed_validation_or_execution"):
            panel._run_stage("primary", packet, tmp_path, [])
    else:
        _, receipt = panel._run_stage("primary", packet, tmp_path, [])
        assert receipt["status"] == "completed"
        assert receipt["actual_model_id"] == panel.MODEL_ID
        assert receipt["model_version"] == "alias_unresolved"
    raw = (tmp_path / "primary/stdout.jsonl").read_bytes()
    assert raw == captured[0] and b"code-mode host is disabled" in raw
    receipt = json.loads((tmp_path / "primary/execution.json").read_bytes())
    assert receipt["stdout_sha256"] == hashlib.sha256(raw).hexdigest()
