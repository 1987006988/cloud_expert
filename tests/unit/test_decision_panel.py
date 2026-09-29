"""Synthetic-only adapter tests. No model, provider, or shared business DB calls."""

import hashlib
import json
import os
import subprocess
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.decision import (
    CandidateDecisionResult,
    DecisionRun,
    DecisionScenario,
    DimensionScore,
    RuleEvaluation,
    ScenarioRequirement,
    ScoringPolicy,
)
from cloud_expert.database.models.evidence_package import EvidencePackage
from cloud_expert.database.models.mapping import (
    MappingCandidate,
    MappingCandidateEvidence,
    MappingRuleSet,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.database.models.tco import (
    CostCalculationRun,
    CostLineItem,
    PricingScenario,
    TCOResult,
)
from cloud_expert.model_review import decision_panel as panel
from cloud_expert.model_review.schemas import Decision
from cloud_expert.pricing import scoped_tco
from tests.unit.test_huawei_price_promotion import component_input, promotion_input  # noqa: F401
from tests.unit.test_policy_costs import (  # noqa: F401
    isolated_policy_registry,
    policy_registry_entries,
)
from tests.unit.test_scoped_tco import scoped_inputs  # noqa: F401


@pytest.fixture
def graph(tmp_path, monkeypatch):
    """Detached ORM graph plus synthetic source file; no production facts inserted."""
    now = datetime.now(UTC) - timedelta(minutes=1)
    raw = b"Synthetic public excerpt for adapter tests only."
    (tmp_path / "raw.txt").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    provider = Provider(id=1, code="synthetic", provider_type="fixture")
    product = Product(id=2, provider_id=1, code="synthetic", market_mode="domestic")
    partition = CloudPartition(
        id=1, partition_code="huawei_cn", provider_id=1, market_mode="domestic"
    )
    region = Region(
        id=1,
        provider_id=1,
        code="synthetic-cn",
        country_code="CN",
        market_mode="domestic",
        is_active=True,
        cloud_partition=partition,
    )
    document = SourceDocument(
        id=1,
        provider_id=1,
        url="https://example.invalid/synthetic",
        source_type="documentation",
        authority_level="official_primary",
        cloud_partition="huawei_cn",
        is_current=True,
        captured_at=now,
        content_hash=digest,
    )
    evidence = Evidence(
        id=1,
        source_document_id=1,
        source_document=document,
        snapshot_record_id=1,
        excerpt=raw.decode(),
        locator="text:synthetic",
        content_hash=digest,
        review_status="machine_extracted",
    )
    snapshot = SnapshotRecord(
        id=1,
        source_document_id=1,
        content_hash=digest,
        storage_path="raw.txt",
        source_id="synthetic",
        captured_at=now,
        is_current=True,
    )
    sku = PriceSKU(
        id=1,
        provider_id=1,
        product_id=2,
        region=region,
        region_id=1,
        billing_unit="instance-hour",
        currency="CNY",
        tax_included=True,
        provider_price_code="synthetic",
        charge_category="compute",
        billing_mode="on_demand",
    )
    region.provider = provider
    sku.product = product
    product.provider = provider
    price = PriceSnapshot(
        id=1,
        price_sku_id=1,
        price_sku=sku,
        evidence_id=1,
        evidence=evidence,
        unit_price=Decimal("2"),
        captured_at=now,
        discount_type="list",
    )
    pricing = PricingScenario(
        id=1,
        scenario_version="v1",
        market_mode="domestic",
        billing_period="monthly",
        target_currency="CNY",
        workload_profile={"compute_instance_hours": 1, "required_cost_dimensions": ["compute"]},
        assumptions={"tax_scope": "tax_included"},
    )
    cost_run = CostCalculationRun(
        id=1,
        scenario_id=1,
        scenario=pricing,
        status="succeeded",
        completed_at=now,
        price_snapshot_cutoff=now,
        rule_version="synthetic-v1",
    )
    tco = TCOResult(
        id=1,
        provider_id=1,
        provider=provider,
        product_id=2,
        product=product,
        scenario_id=1,
        scenario=pricing,
        run_id=1,
        run=cost_run,
        currency="CNY",
        billing_period="monthly",
        subtotal=Decimal("2"),
        total=Decimal("2"),
        completeness_status="complete",
        freshness_status="fresh",
        comparability_status="comparable",
        missing_price_count=0,
    )
    line = CostLineItem(
        id=1,
        run_id=1,
        provider_id=1,
        product_id=2,
        price_sku_id=1,
        price_snapshot_id=1,
        price_snapshot=price,
        evidence_id=1,
        dimension="compute",
        usage_quantity=Decimal(1),
        usage_unit="instance-hour",
        unit_price=Decimal(2),
        amount=Decimal(2),
        currency="CNY",
        tax_status="tax_included",
    )
    policy = ScoringPolicy(
        id=1, policy_version="v1", status="active", rules=[], dimension_weights={"cost": 1}
    )
    scenario = DecisionScenario(
        id=1,
        scenario_version="v1",
        market_mode="domestic",
        country_code="CN",
        preferred_regions=["synthetic-cn"],
        workload_profile={"monthly_hours": 1},
        operational_requirements={"public_evidence_only": True},
        budget_preferences={"currency": "CNY"},
        scoring_policy_id=1,
        status="active",
    )
    requirement = ScenarioRequirement(
        id=1,
        scenario_id=1,
        requirement_type="cost",
        is_mandatory=True,
        required_value={"completeness_status": "complete"},
    )
    scenario.requirements = [requirement]
    run = DecisionRun(
        id=1,
        scenario=scenario,
        policy=policy,
        scenario_version="v1",
        policy_version="v1",
        status="succeeded",
        generated_at=now,
        price_cutoff=now,
        evidence_cutoff=now,
    )
    mapping = MappingCandidate(
        id=1,
        mapping_level="product",
        target_entity_type="product",
        target_entity_id=2,
        target_provider_id=1,
        candidate_status="approved",
        rule_set=MappingRuleSet(id=1, market_mode="domestic"),
        blocking_reasons=[],
        conditions=["Category only; no SKU equivalence."],
    )
    mapping.evidence_links = [MappingCandidateEvidence(id=1, evidence=evidence, evidence_id=1)]
    package = EvidencePackage(id=1, mapping_candidate_id=1, market_mode="domestic", items=[])
    dimension = DimensionScore(
        id=1,
        dimension="cost",
        status="scored",
        weight=Decimal(1),
        normalized_score=Decimal(1),
        weighted_score=Decimal(1),
        evidence_package=package,
        evidence_package_id=1,
    )
    evaluation = RuleEvaluation(
        id=1,
        requirement_id=1,
        requirement=requirement,
        result_status="pass",
        hard_block=False,
        evidence_reference_ids=[1],
        observed_value={"completeness_status": "complete"},
        expected_value={"completeness_status": "complete"},
    )
    result = CandidateDecisionResult(
        id=1,
        decision_run=run,
        mapping_candidate=mapping,
        tco_result=tco,
        tco_result_id=1,
        provider_id=1,
        entity_type="product",
        entity_id=2,
        valid_from=now,
        decision_status="requires_review",
        review_status="machine_generated",
        hard_block_count=0,
        missing_information=[],
        dimension_scores=[dimension],
        rule_evaluations=[evaluation],
    )
    objects = {
        (CandidateDecisionResult, 1): result,
        (Evidence, 1): evidence,
        (SnapshotRecord, 1): snapshot,
    }
    session = Mock(new=set(), dirty=set(), deleted=set(), no_autoflush=nullcontext())
    session.get.side_effect = lambda cls, pk: objects.get((cls, pk))

    class ScalarRows(list):
        def all(self):
            return self

    session.scalars.side_effect = lambda *_: ScalarRows([line])
    monkeypatch.setattr(panel, "OFFICIAL_HOSTS", ("example.invalid",))
    monkeypatch.setattr(
        panel,
        "mapping_approval",
        lambda *_: {
            "event_id": 7,
            "model_id": panel.MODEL_ID,
            "review_state": "model_approved_with_conditions",
            "approved_scope": "product_category_only",
            "subject_hash": "a" * 64,
            "conditions_enforced": True,
        },
    )
    monkeypatch.setattr(panel, "package_currently_eligible", lambda *_: True)
    monkeypatch.setattr(panel, "_current_run", lambda *_: True)
    return SimpleNamespace(**locals())


def _packet(graph):
    return panel.build_decision_packet(graph.session, 1, raw_root=graph.tmp_path)


@pytest.fixture
def packet():
    # The classification is only a mocked orchestration input, never a real evidence approval.
    payload = {
        "target_id": 1,
        "evidence": [{"evidence_id": 1}],
        "input_fingerprint": "a" * 64,
        "data_classification": "official_public",
        "synthetic_test_only": True,
    }
    return panel.DecisionPacket(json.dumps(payload), "{}", "a" * 64, datetime.now(UTC).isoformat())


def _opinion(packet, stage="primary", decision="model_approved", **overrides):
    value = {
        "stage": stage,
        "target_id": 1,
        "input_fingerprint": packet.fingerprint,
        "decision": decision,
        "approved_scope": "scenario_decision_only",
        "comparative_advantage_claimed": False,
        "limitations": [],
        "checks": dict.fromkeys(panel.Checks.model_fields, True),
        "confidence": 0.9,
        "evidence_references": [1],
        "conditions": [],
        "blocking_reasons": [],
        "required_repairs": [],
        "unresolved_questions": [],
        "reasoning_summary": "Synthetic review only.",
    }
    value.update(overrides)
    return value


def test_packet_exact_links_minimization_hash_and_no_writes(graph):
    first = _packet(graph)
    assert first.payload["data_classification"] == "synthetic"
    assert first.payload["tco"]["lines"][0]["evidence_id"] == 1
    assert first.payload["mapping"]["approval"]["approved_scope"] == "product_category_only"
    assert "storage_path" not in first.payload_json
    assert "source_payload_path" not in first.payload_json
    assert "explanation" not in first.payload_json  # No hidden generator reasoning.
    graph.scenario.name = "Excluded local narrative"
    second = _packet(graph)
    assert first.fingerprint != second.fingerprint
    assert "Excluded local narrative" not in second.payload_json
    graph.session.commit.assert_not_called()
    graph.session.flush.assert_not_called()


@pytest.mark.parametrize(
    "object_name,field,value,code",
    [
        ("result", "superseded_by_id", 99, "decision_stale_or_blocked"),
        ("result", "hard_block_count", 1, "decision_stale_or_blocked"),
        ("result", "valid_to", datetime(2020, 1, 1, tzinfo=UTC), "decision_stale_or_blocked"),
        ("result", "entity_id", 999, "decision_mapping_mismatch"),
        ("result", "tco_result", None, "exact_tco_missing"),
        ("scenario", "operational_requirements", {}, "public_only_scenario_required"),
        ("scenario", "preferred_regions", [], "explicit_market_region_required"),
        (
            "scenario",
            "workload_profile",
            {"monthly_hours": 730},
            "tco_incomplete_or_wrong_scenario",
        ),
        ("scenario", "budget_preferences", {"currency": "USD"}, "tco_incomplete_or_wrong_scenario"),
        ("run", "policy_version", "old", "decision_rule_version_invalid"),
        ("line", "amount", Decimal(0), "tco_incomplete_or_wrong_scenario"),
        ("price", "discount_type", "contract", "price_stale_or_nonpublic"),
        ("dimension", "status", "requires_review", "dimension_unresolved"),
        ("evaluation", "hard_block", True, "mandatory_requirements_not_proven"),
        ("evaluation", "observed_value", None, "required_field_support_missing"),
        ("dimension", "weighted_score", Decimal("0.5"), "dimension_arithmetic_or_weight_invalid"),
        ("document", "is_current", False, "evidence_stale_or_incompatible"),
        (
            "document",
            "url",
            "https://example.invalid/?token=private",
            "evidence_not_public_official",
        ),
        (
            "document",
            "captured_at",
            datetime(2020, 1, 1, tzinfo=UTC),
            "evidence_stale_or_incompatible",
        ),
        ("evidence", "content_hash", "wrong", "evidence_content_hash_missing_or_invalid"),
        ("region", "country_code", "US", "tco_incomplete_or_wrong_scenario"),
    ],
)
def test_packet_preconditions_fail_closed(graph, object_name, field, value, code):
    setattr(getattr(graph, object_name), field, value)
    with pytest.raises(ValueError, match=code):
        _packet(graph)


def test_missing_mapping_approval_and_package(graph, monkeypatch):
    monkeypatch.setattr(panel, "package_currently_eligible", lambda *_: False)
    with pytest.raises(ValueError, match="dimension_evidence_package_invalid"):
        _packet(graph)
    monkeypatch.setattr(panel, "mapping_approval", lambda *_: None)
    with pytest.raises(ValueError, match="mapping_approval_missing_or_outdated"):
        _packet(graph)


def test_raw_hash_and_sensitive_content_rejected(graph):
    (graph.tmp_path / "raw.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="raw_snapshot_hash_mismatch"):
        _packet(graph)
    (graph.tmp_path / "raw.txt").write_bytes(graph.raw)
    graph.scenario.workload_profile = {"monthly_hours": 1, "customer_name": "synthetic-secret"}
    with pytest.raises(ValueError, match="sensitive_content_rejected"):
        _packet(graph)


def test_pending_session_cannot_flush(graph):
    graph.session.new = {object()}
    with pytest.raises(ValueError, match="session_has_pending_writes"):
        _packet(graph)
    graph.session.flush.assert_not_called()


def test_old_engine_and_unexecuted_mandatory_requirement_fail_closed(graph, monkeypatch):
    graph.evaluation.result_status = "not_applicable"
    with pytest.raises(ValueError, match="mandatory_requirements_not_proven"):
        _packet(graph)
    graph.evaluation.result_status = "pass"
    monkeypatch.setattr(panel, "_current_run", lambda *_: False)
    with pytest.raises(ValueError, match="decision_engine_or_dependencies_outdated"):
        _packet(graph)


def test_current_run_uses_live_engine_fingerprint(monkeypatch):
    result = SimpleNamespace(
        mapping_candidate_id=1,
        decision_run=SimpleNamespace(scenario=object(), policy=object(), content_hash="old"),
    )
    monkeypatch.setattr(panel.decision_engine, "_candidate_query", lambda _: "query")
    fingerprint = Mock(return_value="current")
    monkeypatch.setattr(panel.decision_engine, "_dependency_fingerprint", fingerprint)
    session = Mock()
    session.scalars.return_value = [SimpleNamespace(id=1)]
    assert not panel._current_run(session, result)
    result.decision_run.content_hash = "current"
    assert panel._current_run(session, result)
    fingerprint.assert_called()


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": "unsupported"},
        {"evidence_references": [999]},
        {"target_id": 2},
        {"input_fingerprint": "b" * 64},
        {"confidence": 1.5},
        {"evidence_references": []},
        {"stage": "adversarial"},
        {"decision": "human_reviewed"},
        {"blocking_reasons": ["missing price"]},
        {"required_repairs": ["reparse"]},
        {"unresolved_questions": ["tax unknown"]},
        {"conditions": ["conditional"]},
        {"decision": "model_approved_with_conditions"},
        {"checks": dict.fromkeys(panel.Checks.model_fields, "true")},
        {"checks": dict.fromkeys(panel.Checks.model_fields, False)},
    ],
)
def test_invalid_model_output(packet, mutation):
    with pytest.raises(ValueError):
        panel.validate_opinion(json.dumps(_opinion(packet, **mutation)), packet, "primary")


def test_independent_prompts_and_conservative_resolution(packet):
    primary = panel.validate_opinion(json.dumps(_opinion(packet)), packet, "primary")
    other = panel.validate_opinion(
        json.dumps(_opinion(packet, "adversarial", "model_inconclusive")), packet, "adversarial"
    )
    assert "independent_opinions" not in panel._prompt("adversarial", packet, [])
    with pytest.raises(ValueError, match="independent_stage_cannot_receive_opinions"):
        panel._prompt("adversarial", packet, [primary])
    arb = panel.validate_opinion(json.dumps(_opinion(packet, "arbitration")), packet, "arbitration")
    assert panel.resolve_panel_opinions(primary, other, arb) == Decision.INCONCLUSIVE
    assert panel.resolve_panel_opinions(primary, other, None) == Decision.INCONCLUSIVE


def test_default_report_only_and_immutable_attempts(graph, monkeypatch):
    probe = Mock(side_effect=AssertionError("No paid calls in a default run"))
    monkeypatch.setattr(panel, "probe_codex_cli", probe)
    first = panel.run_decision_panel(
        graph.session, 1, graph.tmp_path / "reports", raw_root=graph.tmp_path
    )
    second = panel.run_decision_panel(
        graph.session, 1, graph.tmp_path / "reports", raw_root=graph.tmp_path
    )
    assert first["status"] == second["status"] == "ready_not_executed"
    assert first["report_dir"] != second["report_dir"]
    assert not first["database_writeback"] and not first["customer_eligible"]
    manifest = json.loads((Path(first["report_dir"]) / "manifest.json").read_text())
    for name, expected in manifest["artifact_sha256"].items():
        assert (
            hashlib.sha256((Path(first["report_dir"]) / name).read_bytes()).hexdigest() == expected
        )
    assert not manifest["snapshot_pinned"] and manifest["release_evaluation_required"]
    probe.assert_not_called()


def test_synthetic_packet_cannot_execute_models(graph, monkeypatch):
    probe = Mock()
    monkeypatch.setattr(panel, "probe_codex_cli", probe)
    result = panel.run_decision_panel(
        graph.session, 1, graph.tmp_path / "reports", raw_root=graph.tmp_path, execute_models=True
    )
    assert result["reason_code"] == "synthetic_live_review_prohibited"
    probe.assert_not_called()


@pytest.fixture(autouse=True)
def isolated_codex_home(monkeypatch, tmp_path):
    home = tmp_path / "synthetic-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def _cli_stub(
    monkeypatch,
    packet,
    *,
    raw=None,
    extra_events=None,
    failure=None,
    mutate_native=None,
    no_native=False,
    duplicate_native=False,
):
    calls = []
    monkeypatch.setattr(panel.shutil, "which", lambda _: "codex")

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        if failure:
            raise failure
        prompt = kwargs["input"].decode("utf-8")
        stage = next(
            s for s in ("primary", "adversarial", "arbitration") if f"stage={s}." in prompt
        )
        response = raw if raw is not None else json.dumps(_opinion(packet, stage))
        Path(command[command.index("-o") + 1]).write_bytes(response.encode("utf-8") + b"\r\n")
        session_id, turn_id = str(uuid4()), str(uuid4())
        events = [
            {"type": "thread.started", "thread_id": session_id},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "id": "item_0", "text": response},
            },
            {"type": "turn.completed"},
        ] + (extra_events or [])
        now = datetime.now(UTC)
        cwd = str(kwargs["cwd"])
        native = [
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": cwd,
                    "model_provider": "openai",
                    "cli_version": "0.158.0-synthetic",
                    "parent_thread_id": None,
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_started",
                    "turn_id": turn_id,
                    "root_turn_id": turn_id,
                },
            },
            {
                "type": "turn_context",
                "payload": {
                    "turn_id": turn_id,
                    "model": panel.MODEL_ID,
                    "effort": "max",
                    "cwd": cwd,
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "channel": "final",
                    "content": [{"type": "output_text", "text": response}],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": response,
                },
            },
        ]
        for event in native:
            event["timestamp"] = now.isoformat()
        if mutate_native:
            mutate_native(native)
        if not no_native:
            directory = Path(os.environ["CODEX_HOME"]) / "sessions" / now.strftime("%Y/%m/%d")
            directory.mkdir(parents=True, exist_ok=True)
            encoded = b"\r\n".join(json.dumps(e).encode("utf-8") for e in native) + b"\r\n"
            (directory / f"rollout-{now:%Y-%m-%dT%H-%M-%S}-{session_id}.jsonl").write_bytes(encoded)
            if duplicate_native:
                (directory / f"rollout-duplicate-{session_id}.jsonl").write_bytes(encoded)
        stdout = b"\r\n".join(json.dumps(e).encode("utf-8") for e in events) + b"\r\n"
        return subprocess.CompletedProcess(command, 0, stdout, b"synthetic stderr\r\n")

    monkeypatch.setattr(panel.subprocess, "run", execute)
    return calls


def test_real_adapter_command_provenance_and_independent_context(packet, tmp_path, monkeypatch):
    calls = _cli_stub(monkeypatch, packet)
    _, first = panel._run_stage("primary", packet, tmp_path, [])
    _, second = panel._run_stage("adversarial", packet, tmp_path, [])
    assert first["session_id"] != second["session_id"]
    assert calls[0][1]["cwd"] != calls[1][1]["cwd"]
    assert b"independent_opinions" not in calls[1][1]["input"]
    assert b"Synthetic review only." not in calls[1][1]["input"]
    assert "--ignore-user-config" in calls[0][0] and "--ephemeral" not in calls[0][0]
    for stage, receipt in (("primary", first), ("adversarial", second)):
        assert receipt["argv"][receipt["argv"].index("-m") + 1] == panel.MODEL_ID
        assert receipt["reasoning_effort"] == "max"
        assert receipt["status"] == "completed" and receipt["response_id"] == "item_0"
        assert receipt["started_at"] <= receipt["completed_at"]
        assert receipt["actual_model_id"] == panel.MODEL_ID
        assert receipt["model_provider"] == "openai"
        assert receipt["model_version"] == "alias_unresolved" and not receipt["fallback_used"]
        meta = panel.audit_bundle.ExecutionMetadata.model_validate(receipt)
        refs = panel.audit_bundle.StageArtifacts.model_validate(
            json.loads((tmp_path / stage / "artifacts.json").read_bytes())
        )
        assert refs.runtime_identity is not None
        reader = panel.audit_bundle._Reader(tmp_path)
        prompt = (tmp_path / stage / "prompt.txt").read_bytes().decode("utf-8")
        panel.audit_bundle._runtime_identity(
            reader,
            refs.runtime_identity,
            meta,
            prompt,
            reader.ref(refs.response),
            datetime.now(UTC).isoformat(),
        )
        stdout, stderr = reader.ref(refs.trace), reader.ref(refs.stderr)
        assert b"\r\n" in stdout and stderr == b"synthetic stderr\r\n"
        assert hashlib.sha256(stdout).hexdigest() == receipt["stdout_sha256"]
        assert hashlib.sha256(stderr).hexdigest() == receipt["stderr_sha256"]
        panel.audit_bundle._trace(
            stdout, reader.ref(refs.response), meta, runtime_identity_verified=True
        )
        capture = json.loads(reader.ref(refs.runtime_identity.capture))
        assert capture["session_id"] == receipt["session_id"]
        assert capture["audit_id"] == receipt["audit_id"]
        assert receipt["completed_at"] <= capture["captured_at"]
        assert "/" not in capture["source_basename"]
        assert json.loads((tmp_path / stage / "privacy.json").read_bytes())["status"] == "passed"
        assert (
            receipt["response_sha256"]
            == hashlib.sha256((tmp_path / stage / "response.raw.json").read_bytes()).hexdigest()
        )
        assert (
            receipt["prompt_sha256"]
            == hashlib.sha256((tmp_path / stage / "prompt.txt").read_bytes()).hexdigest()
        )


@pytest.mark.parametrize("failure_type", ["invalid_json", "tool_use", "timeout", "no_attestation"])
def test_execution_failure_is_audited(packet, tmp_path, monkeypatch, failure_type):
    extras = (
        [{"type": "item.completed", "item": {"type": "command_execution", "id": "bad"}}]
        if failure_type == "tool_use"
        else []
    )
    _cli_stub(
        monkeypatch,
        packet,
        raw="{broken" if failure_type == "invalid_json" else None,
        extra_events=extras,
        failure=subprocess.TimeoutExpired("codex", 360) if failure_type == "timeout" else None,
    )
    if failure_type == "no_attestation":
        monkeypatch.setattr(
            panel.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"private stderr"),
        )
    with pytest.raises(RuntimeError):
        panel._run_stage("primary", packet, tmp_path, [])
    receipt = json.loads((tmp_path / "primary/execution.json").read_text())
    assert receipt["status"] == "failed" and receipt["completed_at"]
    assert "private stderr" not in json.dumps(receipt)
    if failure_type == "invalid_json":
        assert (tmp_path / "primary/response.raw.json").read_bytes() == b"{broken\r\n"


@pytest.mark.parametrize(
    "mutation",
    [
        "model",
        "provider",
        "session",
        "turn",
        "cwd",
        "effort",
        "input",
        "response",
        "prior_turn",
        "old_timestamp",
        "fallback",
        "tool",
        "compacted",
        "incomplete",
        "account_metadata",
        "secret_metadata",
        "missing_context",
    ],
)
def test_native_identity_fails_closed(packet, tmp_path, monkeypatch, mutation):
    def mutate(events):
        meta, context = events[0]["payload"], events[2]["payload"]
        if mutation == "model":
            context["model"] = "not-the-approved-model"
        elif mutation == "provider":
            meta["model_provider"] = "other"
        elif mutation == "session":
            meta["id"] = str(uuid4())
        elif mutation == "turn":
            context["turn_id"] = str(uuid4())
        elif mutation == "cwd":
            context["cwd"] = str(tmp_path / "other")
        elif mutation == "effort":
            context["effort"] = "low"
        elif mutation == "input":
            events[3]["payload"]["content"][0]["text"] = "Prior unrelated private context."
        elif mutation == "response":
            events[-1]["payload"]["last_agent_message"] = "Changed response."
        elif mutation == "prior_turn":
            meta["parent_thread_id"] = str(uuid4())
        elif mutation == "old_timestamp":
            events[0]["timestamp"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        elif mutation == "fallback":
            context["fallback_used"] = True
        elif mutation == "tool":
            events[4]["payload"]["type"] = "function_call"
        elif mutation == "compacted":
            events[4]["type"] = "compacted"
        elif mutation == "incomplete":
            events.pop()
        elif mutation == "account_metadata":
            meta["chatgpt_account_id"] = "synthetic-private-account"
        elif mutation == "secret_metadata":
            meta["api_key"] = "synthetic-secret-do-not-share"
        elif mutation == "missing_context":
            events.pop(2)

    _cli_stub(monkeypatch, packet, mutate_native=mutate)
    with pytest.raises(RuntimeError):
        panel._run_stage("primary", packet, tmp_path, [])
    stage = tmp_path / "primary"
    assert json.loads((stage / "execution.json").read_bytes())["status"] == "failed"
    assert (stage / "runtime.native.jsonl").is_file()
    assert (stage / "response.raw.json").is_file()
    assert not (stage / "response.json").exists()
    assert not (stage / "artifacts.json").exists()
    if mutation.endswith("metadata"):
        privacy = json.loads((stage / "privacy.json").read_bytes())
        assert privacy["status"] == "blocked" and not privacy["transmit_to_model"]
        assert "synthetic-secret" not in json.dumps(privacy)


@pytest.mark.parametrize("kind", ["missing", "ambiguous", "old", "hardlink"])
def test_native_locator_rejects_unattested_files(packet, tmp_path, monkeypatch, kind):
    _cli_stub(
        monkeypatch, packet, no_native=kind == "missing", duplicate_native=kind == "ambiguous"
    )
    execute = panel.subprocess.run

    def wrapped(*args, **kwargs):
        result = execute(*args, **kwargs)
        if kind in {"old", "hardlink"}:
            sid = json.loads(result.stdout.splitlines()[0])["thread_id"]
            path = next(
                Path(os.environ["CODEX_HOME"]).glob(f"sessions/*/*/*/rollout-*-{sid}.jsonl")
            )
            if kind == "old":
                old = (datetime.now(UTC) - timedelta(days=1)).timestamp()
                os.utime(path, (old, old))
            else:
                os.link(path, path.with_suffix(".linked"))
        return result

    monkeypatch.setattr(panel.subprocess, "run", wrapped)
    with pytest.raises(RuntimeError):
        panel._run_stage("primary", packet, tmp_path, [])
    receipt = json.loads((tmp_path / "primary/execution.json").read_bytes())
    assert receipt["status"] == "failed"
    assert receipt["reason_code"].startswith("runtime_")
    assert not (tmp_path / "primary/runtime.native.jsonl").exists()


def test_capture_never_reads_auth_or_other_sessions(
    packet, tmp_path, monkeypatch, isolated_codex_home
):
    directory = isolated_codex_home / "sessions" / datetime.now(UTC).strftime("%Y/%m/%d")
    directory.mkdir(parents=True)
    unrelated = directory / f"rollout-unrelated-{uuid4()}.jsonl"
    unrelated.write_bytes(b"never read other session bytes")
    auth = isolated_codex_home / "auth.json"
    auth.write_bytes(b"never read auth")
    original_open = Path.open
    accessed = []

    def guarded_open(path, *args, **kwargs):
        assert path not in {auth, unrelated}, "Attempt to read an unrelated private file"
        accessed.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    _cli_stub(monkeypatch, packet)
    _, receipt = panel._run_stage("primary", packet, tmp_path, [])
    captured = tmp_path / "primary/runtime.native.jsonl"
    originals = [p for p in accessed if p.name.endswith(f"-{receipt['session_id']}.jsonl")]
    assert len(originals) >= 1
    assert originals[-1].read_bytes() == captured.read_bytes()
    with pytest.raises(OSError):
        panel._write_bytes(captured, b"overwrite prohibited")


def test_timeout_preserves_partial_streams_and_scans_secrets(packet, tmp_path, monkeypatch):
    partial = b'{"api_key":"synthetic-private-value"}\r\n'
    _cli_stub(
        monkeypatch,
        packet,
        failure=subprocess.TimeoutExpired(
            "codex",
            360,
            output=partial,
            stderr=b"incomplete\r\n",
        ),
    )
    with pytest.raises(RuntimeError):
        panel._run_stage("primary", packet, tmp_path, [])
    stage = tmp_path / "primary"
    assert (stage / "stdout.jsonl").read_bytes() == partial
    assert (stage / "stderr.txt").read_bytes() == b"incomplete\r\n"
    assert json.loads((stage / "privacy.json").read_bytes())["status"] == "blocked"


AUTH = {
    "external_data_transfer_approved": True,
    "approved_model": panel.MODEL_ID,
    "approved_payload_classes": ["official_source_excerpts", "necessary_identifiers"],
}


@pytest.mark.parametrize(
    "adversarial_decision,expected_calls,final",
    [
        ("model_approved", 2, "model_approved"),
        ("model_inconclusive", 3, "model_inconclusive"),
        ("model_blocked", 3, "model_inconclusive"),
    ],
)
def test_orchestration_and_arbitration(
    packet, tmp_path, monkeypatch, adversarial_decision, expected_calls, final
):
    monkeypatch.setattr(panel, "build_decision_packet", lambda *a, **k: packet)
    monkeypatch.setattr(panel, "probe_codex_cli", lambda *_: {"available": True})
    seen = []

    def stage(name, passed_packet, run_dir, opinions):
        seen.append((name, opinions))
        decision = adversarial_decision if name == "adversarial" else "model_approved"
        parsed = panel.validate_opinion(json.dumps(_opinion(packet, name, decision)), packet, name)
        return parsed, {"session_id": str(uuid4()), "status": "completed", "stage": name}

    monkeypatch.setattr(panel, "_run_stage", stage)
    result = panel.run_decision_panel(Mock(), 1, tmp_path, execute_models=True, authorization=AUTH)
    assert result["status"] == "completed" and result["final_decision"] == final
    assert len(seen) == expected_calls
    assert seen[0] == ("primary", []) and seen[1] == ("adversarial", [])
    if expected_calls == 3:
        assert len(seen[2][1]) == 2
    assert not result["customer_eligible"] and not result["model_version_gate_passed"]


def test_changed_subject_or_reused_session_not_approved(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "build_decision_packet", lambda *a, **k: packet)
    monkeypatch.setattr(panel, "probe_codex_cli", lambda *_: {"available": True})
    same_session = str(uuid4())
    monkeypatch.setattr(
        panel,
        "_run_stage",
        lambda name, *_: (
            panel.validate_opinion(json.dumps(_opinion(packet, name)), packet, name),
            {"session_id": same_session},
        ),
    )
    result = panel.run_decision_panel(Mock(), 1, tmp_path, execute_models=True, authorization=AUTH)
    assert result["final_decision"] == "model_inconclusive"
    assert result["reason_code"] == "review_sessions_not_independent"
    monkeypatch.setattr(
        panel,
        "_run_stage",
        lambda name, *_: (
            panel.validate_opinion(json.dumps(_opinion(packet, name)), packet, name),
            {"session_id": str(uuid4())},
        ),
    )
    changed = panel.DecisionPacket(packet.payload_json, "{}", "b" * 64, packet.checked_at)
    monkeypatch.setattr(panel, "build_decision_packet", Mock(side_effect=[packet, changed]))
    result = panel.run_decision_panel(Mock(), 1, tmp_path, execute_models=True, authorization=AUTH)
    assert result["reason_code"] == "subject_changed_during_review"


def test_authorization_and_probe_failure_no_review(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "build_decision_packet", lambda *a, **k: packet)
    stage = Mock(side_effect=AssertionError("No review may start"))
    monkeypatch.setattr(panel, "_run_stage", stage)
    result = panel.run_decision_panel(Mock(), 1, tmp_path, execute_models=True)
    assert result["reason_code"] == "external_review_not_authorized"
    monkeypatch.setattr(panel, "probe_codex_cli", lambda *_: {"available": False})
    result = panel.run_decision_panel(Mock(), 1, tmp_path, execute_models=True, authorization=AUTH)
    assert result["reason_code"] == "highest_model_probe_failed"
    stage.assert_not_called()


def test_conditions_cannot_be_dropped_by_arbitration(packet):
    primary = panel.validate_opinion(
        json.dumps(
            _opinion(
                packet, decision="model_approved_with_conditions", conditions=["Category only"]
            )
        ),
        packet,
        "primary",
    )
    adversarial = panel.validate_opinion(
        json.dumps(
            _opinion(
                packet,
                "adversarial",
                "model_approved_with_conditions",
                conditions=["Exact usage only"],
            )
        ),
        packet,
        "adversarial",
    )
    arb = panel.validate_opinion(json.dumps(_opinion(packet, "arbitration")), packet, "arbitration")
    assert panel.resolve_panel_opinions(primary, adversarial, arb) == Decision.INCONCLUSIVE
    arb = panel.validate_opinion(
        json.dumps(
            _opinion(
                packet,
                "arbitration",
                "model_approved_with_conditions",
                conditions=["Category only", "Exact usage only"],
            )
        ),
        packet,
        "arbitration",
    )
    assert panel.resolve_panel_opinions(primary, adversarial, arb) == Decision.CONDITIONAL


@pytest.mark.parametrize(
    "value",
    [
        {"token": "never-send"},
        {"excerpt": '{"account_id":"never-send"}'},
        {"excerpt": '{"X-Auth-Token":"never-send"}'},
        {"excerpt": '{"api_key":"never-send"}'},
    ],
)
def test_nested_secret_keys_and_account_response_rejected(value):
    with pytest.raises(ValueError, match="sensitive_content_rejected"):
        panel._public(value)


def test_model_policy_never_falls_back(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "build_decision_packet", lambda *a, **k: packet)
    monkeypatch.setattr(panel, "load_registry", lambda _: ([], True))
    probe = Mock(side_effect=AssertionError("Must fail before probe"))
    monkeypatch.setattr(panel, "probe_codex_cli", probe)
    result = panel.run_decision_panel(Mock(), 1, tmp_path, execute_models=True, authorization=AUTH)
    assert result["reason_code"] == "highest_model_policy_blocked"
    probe.assert_not_called()


@pytest.fixture
def scoped_graph(graph, monkeypatch):
    # Packet projection tests use a mocked validator; the test below exercises its real implementation.
    graph.result.output_level = "internal_only"
    graph.result.customer_eligible = False
    graph.tco.comparability_status = "needs_review"
    graph.cost_run.rule_version = panel.SCOPED_TCO_RULE
    context = {"region": "synthetic-cn", "country_code": "CN", "partition": "huawei_cn"}
    rationale = "Synthetic architecture does not deploy backup; no price is asserted."
    graph.pricing.workload_profile = {
        "compute_instance_hours": "1",
        "config_sha256": "b" * 64,
        "scoped_ecs_config": {
            "purpose": "internal_bounded_ecs_cost_research",
            "context": context,
            "costs": [
                {
                    "dimension": "snapshot_backup",
                    "treatment": "not_applicable",
                    "quantity": "0",
                    "rationale": rationale,
                }
            ],
        },
    }
    common = {"missing_prices_are_not_zero": True, "customer_eligible": False}
    policy_line = CostLineItem(
        id=2,
        run_id=1,
        product_id=2,
        provider_id=1,
        dimension="support",
        amount=Decimal(0),
        unit_price=Decimal(0),
        usage_quantity=Decimal(1),
        usage_unit="scenario",
        currency="CNY",
        tax_status="tax_included",
        evidence_id=1,
        assumptions={
            **common,
            "treatment": "policy_zero",
            "rationale": "Synthetic basic support policy.",
            "policy_receipt": {
                "evidence_id": 1,
                "dimension": "support",
                "only_dimension": "support",
                "conditions": context,
                "amount": "0",
                "currency": "CNY",
                "price_snapshot_created": False,
                "customer_eligible": False,
                "captured_at": graph.now.isoformat(),
                "raw_sha256": graph.digest,
                "evidence_sha256": graph.digest,
            },
        },
    )
    excluded_line = CostLineItem(
        id=3,
        run_id=1,
        product_id=2,
        provider_id=1,
        dimension="snapshot_backup",
        amount=Decimal(0),
        usage_quantity=Decimal(0),
        usage_unit="scenario",
        currency="CNY",
        tax_status="tax_included",
        assumptions={**common, "treatment": "not_applicable", "rationale": rationale},
    )
    graph.session.scalars.side_effect = lambda *_: [graph.line, policy_line, excluded_line]
    validator = Mock(return_value=True)
    monkeypatch.setattr(panel, "scoped_tco_result_currently_complete", validator)
    monkeypatch.setattr(panel, "_tco_matches_scenario", lambda *_: True)
    graph.policy_line, graph.excluded_line, graph.validator = policy_line, excluded_line, validator
    return graph


def test_scoped_cost_packet_preserves_policy_zero_exclusions_and_no_equivalence(scoped_graph):
    graph = scoped_graph
    packet = _packet(graph)
    payload = packet.payload
    assert payload["review_scope"] == panel.SCOPED_REVIEW
    assert payload["tco"]["comparability_status"] == "needs_review"
    assert set(panel.SCOPED_LIMITATIONS) <= set(payload["limitations"])
    bounded = payload["tco"]["bounded_cost_review"]
    assert not bounded["comparative_advantage_allowed"]
    assert bounded["disclosed_exclusions"][0]["dimension"] == "snapshot_backup"
    lines = {line["dimension"]: line for line in payload["tco"]["lines"]}
    assert lines["support"]["price_snapshot"] is None
    assert lines["support"]["assumptions"]["policy_receipt"]["evidence_id"] == 1
    assert lines["support"]["evidence_id"] in {item["evidence_id"] for item in payload["evidence"]}
    assert lines["snapshot_backup"]["price_snapshot"] is None
    assert lines["snapshot_backup"]["evidence_id"] is None
    assert lines["snapshot_backup"]["unit_price"] is None
    graph.validator.assert_called_once()
    assert graph.validator.call_args.kwargs["root"] == graph.tmp_path
    assert "now" in graph.validator.call_args.kwargs
    graph.session.flush.assert_not_called()
    graph.session.commit.assert_not_called()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("validator", "scoped_tco_validation_failed"),
        ("customer", "scoped_cost_internal_only_no_comparative_claim"),
        ("rank", "scoped_cost_internal_only_no_comparative_claim"),
        ("output", "scoped_cost_internal_only_no_comparative_claim"),
        ("receipt", "scoped_policy_receipt_missing"),
        ("no_evidence", "scoped_policy_receipt_mismatch"),
        ("wrong_scope", "scoped_policy_receipt_mismatch"),
        ("future_policy", "policy_after_decision_cutoff"),
        ("fake_price", "scoped_nonprice_line_invalid"),
        ("missing", "scoped_nonprice_treatment_unsupported"),
        ("excluded_price", "scoped_exclusion_invalid"),
        ("excluded_evidence", "scoped_exclusion_invalid"),
        ("undisclosed_exclusion", "scoped_exclusion_invalid"),
        ("hardblock", "decision_stale_or_blocked"),
    ],
)
def test_scoped_exception_never_weakens_validation(scoped_graph, mutation, reason):
    graph = scoped_graph
    if mutation == "validator":
        graph.validator.return_value = False
    elif mutation == "customer":
        graph.result.customer_eligible = True
    elif mutation == "rank":
        graph.result.rank = 1
    elif mutation == "output":
        graph.result.output_level = "customer_eligible_candidate"
    elif mutation == "receipt":
        graph.policy_line.assumptions.pop("policy_receipt")
    elif mutation == "no_evidence":
        graph.policy_line.evidence_id = None
    elif mutation == "wrong_scope":
        graph.policy_line.assumptions["policy_receipt"]["conditions"] = {"region": "other"}
    elif mutation == "future_policy":
        graph.policy_line.assumptions["policy_receipt"]["captured_at"] = (
            graph.now + timedelta(days=1)
        ).isoformat()
    elif mutation == "fake_price":
        graph.policy_line.price_snapshot_id = 999
    elif mutation == "missing":
        graph.policy_line.assumptions["treatment"] = "missing"
    elif mutation == "excluded_price":
        graph.excluded_line.unit_price = Decimal(0)
    elif mutation == "excluded_evidence":
        graph.excluded_line.evidence_id = 1
    elif mutation == "undisclosed_exclusion":
        graph.excluded_line.dimension = "unlisted"
    elif mutation == "hardblock":
        graph.result.hard_block_count = 1
    with pytest.raises(ValueError, match=reason):
        _packet(graph)


def test_general_decisions_still_require_comparability_and_price(graph, monkeypatch):
    graph.tco.comparability_status = "needs_review"
    with pytest.raises(ValueError, match="tco_incomplete_or_wrong_scenario"):
        _packet(graph)
    graph.tco.comparability_status = "comparable"
    graph.line.price_snapshot = None
    monkeypatch.setattr(panel, "_tco_matches_scenario", lambda *_: True)
    with pytest.raises(ValueError, match="line_price_missing"):
        _packet(graph)


@pytest.mark.parametrize("mutation", ["advantage", "scope", "limitations"])
def test_scoped_model_cannot_promote_cost_to_advantage(scoped_graph, mutation):
    packet = _packet(scoped_graph)
    response = _opinion(
        packet, approved_scope=panel.SCOPED_REVIEW, limitations=list(panel.SCOPED_LIMITATIONS)
    )
    panel.validate_opinion(json.dumps(response), packet, "primary")
    if mutation == "advantage":
        response["comparative_advantage_claimed"] = True
    elif mutation == "scope":
        response["approved_scope"] = "scenario_decision_only"
    else:
        response["limitations"] = []
    with pytest.raises(ValueError):
        panel.validate_opinion(json.dumps(response), packet, "primary")


def test_scoped_review_uses_real_validator_and_detects_tampering(session, scoped_inputs):  # noqa: F811
    config, store, _ = scoped_inputs
    report = scoped_tco.persist_scoped_tco(session, config, root=store.raw_data_dir)
    session.commit()
    tco = session.query(TCOResult).filter_by(run_id=report["run_id"]).one()
    decision = CandidateDecisionResult(
        tco_result=tco,
        output_level="internal_only",
        customer_eligible=False,
        decision_run=DecisionRun(
            scenario=DecisionScenario(market_mode="domestic", country_code="CN")
        ),
    )
    now = datetime.now(UTC)
    bounded = panel._scoped_cost_review(session, decision, store.raw_data_dir, now)
    assert bounded["review_scope"] == panel.SCOPED_REVIEW
    assert bounded["disclosed_exclusions"]
    policy_line = next(line for line in tco.run.line_items if line.dimension == "support")
    public_line, evidence_id = panel._scoped_nonprice_line(policy_line, bounded, now)
    assert evidence_id is not None and public_line["price_snapshot"] is None
    assert not session.new and not session.dirty
    policy_line.evidence_id = None
    with pytest.raises(ValueError, match="scoped_tco_validation_failed"):
        panel._scoped_cost_review(session, decision, store.raw_data_dir, now)


@pytest.fixture
def catalog_graph(scoped_graph, monkeypatch):
    graph = scoped_graph
    # Synthetic projection fixture; real parser/derivation tests run in the companion suite.
    graph.sku.provider = Provider(id=1, code="aliyun", provider_type="fixture")
    graph.price.discount_type = "estimated"
    derived = {
        "scope": "bounded_catalog_reference_only",
        "realtime": False,
        "customer_approved": False,
        "assumptions": {"duration_hours": 720},
    }
    graph.line.assumptions = {"input_scope": {"derived": derived}}
    graph.evidence.excerpt = json.dumps(derived)
    graph.evidence.content_hash = hashlib.sha256(graph.evidence.excerpt.encode()).hexdigest()
    graph.catalog_validator = Mock(return_value=True)
    monkeypatch.setattr(panel, "catalog_price_valid", graph.catalog_validator)
    return graph


def test_scoped_public_catalog_estimate_preserves_label_and_disclosure(catalog_graph):
    graph = catalog_graph
    packet = _packet(graph)
    line = packet.payload["tco"]["lines"][0]
    assert line["price_snapshot"]["discount_type"] == "estimated"
    assert line["estimated_catalog_disclosure"] == panel.SCOPED_LIMITATIONS[-1]
    assert line["assumptions"]["input_scope"]["derived"]["realtime"] is False
    assert packet.payload["review_scope"] == panel.SCOPED_REVIEW
    assert panel.SCOPED_LIMITATIONS[-1] in packet.payload["limitations"]
    graph.validator.assert_called_once()
    graph.catalog_validator.assert_called_once_with(graph.session, graph.price)
    graph.session.commit.assert_not_called()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("scope", "estimated_catalog_scope_invalid"),
        ("realtime", "estimated_catalog_scope_invalid"),
        ("customer", "estimated_catalog_scope_invalid"),
        ("provider", "estimated_catalog_scope_invalid"),
        ("derivation", "estimated_catalog_scope_invalid"),
        ("catalog_validator", "estimated_catalog_scope_invalid"),
        ("scoped_validator", "scoped_tco_validation_failed"),
        ("stale", "price_stale_or_nonpublic"),
        ("spot", "price_stale_or_nonpublic"),
        ("contract", "price_stale_or_nonpublic"),
        ("unknown", "price_stale_or_nonpublic"),
    ],
)
def test_estimated_catalog_exception_is_bounded(catalog_graph, mutation, reason, monkeypatch):
    graph = catalog_graph
    derived = graph.line.assumptions["input_scope"]["derived"]
    if mutation == "scope":
        derived["scope"] = "all_prices"
    elif mutation == "realtime":
        derived["realtime"] = True
    elif mutation == "customer":
        derived["customer_approved"] = True
    elif mutation == "provider":
        graph.sku.provider.code = "other"
    elif mutation == "derivation":
        derived["assumptions"]["duration_hours"] = 730
    elif mutation == "catalog_validator":
        graph.catalog_validator.return_value = False
    elif mutation == "scoped_validator":
        graph.validator.return_value = False
    elif mutation == "stale":
        monkeypatch.setattr(panel, "price_snapshot_freshness", lambda *a, **k: "stale")
    else:
        graph.price.discount_type = mutation
    with pytest.raises(ValueError, match=reason):
        _packet(graph)


def test_general_decision_never_accepts_estimated_catalog_price(graph, monkeypatch):
    graph.price.discount_type = "estimated"
    validator = Mock(return_value=True)
    monkeypatch.setattr(panel, "catalog_price_valid", validator)
    with pytest.raises(ValueError, match="price_stale_or_nonpublic"):
        _packet(graph)
    validator.assert_not_called()
