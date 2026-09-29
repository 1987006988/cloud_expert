from pathlib import Path
from types import SimpleNamespace

from cloud_expert.model_review import pilot
from cloud_expert.model_review.schemas import AdversarialReview, Decision, PrimaryReview


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


def test_model_input_uses_utf8_stdin_and_not_command_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pilot.shutil, "which", lambda _: "codex.cmd")
    payload = {"target_type": "mapping_candidate", "evidence": [{"evidence_id": 10}]}

    def fake_run(command: list[str], **kwargs):
        assert command[-1] == "-"
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert kwargs["timeout"] == 360
        assert "INPUT_JSON" in kwargs["input"]
        assert not any("mapping_candidate" in argument for argument in command)
        Path(command[command.index("-o") + 1]).write_text(
            PrimaryReview(
                decision=Decision.BLOCKED,
                confidence=1,
                supported_by_evidence=False,
                field_semantics_correct=False,
                scope_correct=False,
                market_scope_correct=False,
                conditions=[],
                blocking_reasons=["Synthetic missing support"],
                required_repairs=[],
                evidence_references=[],
                reasoning_summary="Synthetic review only.",
            ).model_dump_json(),
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=0,
            stderr="session id: 00000000-0000-0000-0000-000000000001",
        )

    monkeypatch.setattr(pilot.subprocess, "run", fake_run)
    result, session_id = pilot._run_stage(
        "primary", payload, PrimaryReview, tmp_path, "synthetic-model"
    )
    assert result.decision == Decision.BLOCKED
    assert session_id == "00000000-0000-0000-0000-000000000001"
