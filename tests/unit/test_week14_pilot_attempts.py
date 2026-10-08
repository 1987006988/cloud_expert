from pathlib import Path

from cloud_expert.model_review import pilot
from cloud_expert.model_review.schemas import AdversarialReview, Decision, PrimaryReview
from tests.unit import test_mapping_pilot_isolation as isolation_tests

mapping_harness = isolation_tests.harness


def test_pilot_preserves_failed_attempt_and_creates_new_directory(
    tmp_path: Path, monkeypatch
) -> None:
    payload = {
        "target_type": "mapping_candidate",
        "target_id": 42,
        "precheck_verdict": "requires_dual_model_review",
        "evidence": [{"evidence_id": 10}],
    }
    monkeypatch.setattr(pilot, "mapping_review_input", lambda *_: payload)
    primary = PrimaryReview(
        decision=Decision.INCONCLUSIVE,
        confidence=0.8,
        supported_by_evidence=False,
        field_semantics_correct=False,
        scope_correct=False,
        market_scope_correct=False,
        conditions=[],
        blocking_reasons=["Synthetic ambiguity"],
        required_repairs=[],
        evidence_references=[10],
        reasoning_summary="Synthetic review only.",
    )
    adversarial = AdversarialReview(
        verdict="agree",
        identified_errors=[],
        missing_conditions=[],
        recommended_decision=Decision.INCONCLUSIVE,
        confidence=0.8,
        evidence_references=[10],
        reasoning_summary="Synthetic review only.",
    )

    def fake_stage(stage: str, *_args):
        if stage == "primary":
            return primary, "primary-session"
        return adversarial, "adversarial-session"

    monkeypatch.setattr(pilot, "_run_stage", fake_stage)
    first = pilot.run_mapping_pilot(None, "synthetic", 42, tmp_path, "synthetic-model")
    second = pilot.run_mapping_pilot(None, "synthetic", 42, tmp_path, "synthetic-model")
    assert first["status"] == second["status"] == "completed"
    assert first["final_decision"] == second["final_decision"] == "model_inconclusive"
    assert first["report_dir"] != second["report_dir"]
    assert Path(first["report_dir"]).is_dir()
    assert Path(second["report_dir"]).name.endswith("_run_02")


def test_model_input_uses_utf8_stdin_and_not_command_line(mapping_harness) -> None:
    mapping_harness.opinions["primary"] = {
        "decision": "model_blocked",
        "confidence": 1,
        "supported_by_evidence": False,
        "field_semantics_correct": False,
        "scope_correct": False,
        "market_scope_correct": False,
        "conditions": [],
        "blocking_reasons": ["Synthetic missing support"],
        "required_repairs": [],
        "evidence_references": [],
        "reasoning_summary": "Synthetic only.",
    }
    result, session_id = pilot._run_stage(
        "primary", mapping_harness.payload, PrimaryReview, mapping_harness.root, "gpt-6-astra"
    )
    command, kwargs = mapping_harness.calls[0]
    assert command[-1] == "-"
    assert "encoding" not in kwargs and "errors" not in kwargs
    assert kwargs["timeout"] == 360
    assert b"INPUT_JSON" in kwargs["input"]
    assert not any("mapping_candidate" in argument for argument in command)
    assert result.decision == Decision.BLOCKED
    assert len(session_id) == 36
