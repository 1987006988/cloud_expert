from dataclasses import replace

from cloud_expert.model_review.registry import ModelCapability, resolve_model


def _model(model_id: str, rank: int) -> ModelCapability:
    return ModelCapability(
        provider="synthetic",
        model_id=model_id,
        model_version="test-v1",
        reasoning_tier="test",
        context_window=100,
        structured_output_supported=True,
        tool_call_supported=True,
        availability="requires_probe",
        approved_for_review=True,
        capability_rank=rank,
        effective_at="2026-01-01T00:00:00Z",
    )


def test_highest_model_requires_successful_probe() -> None:
    highest, lower = _model("highest", 100), _model("lower", 50)
    blocked = resolve_model([lower, highest], verified_available={"lower"})
    assert blocked.status == "BLOCKED"
    assert blocked.model == highest
    assert blocked.fallback_used is False
    available = resolve_model([lower, highest], verified_available={"highest", "lower"})
    assert available.status == "AVAILABLE"
    assert available.model == highest


def test_fallback_requires_explicit_policy_and_approved_model() -> None:
    highest, lower = _model("highest", 100), _model("lower", 50)
    fallback = resolve_model([highest, lower], verified_available={"lower"}, allow_fallback=True)
    assert fallback.status == "AVAILABLE"
    assert fallback.model == lower
    assert fallback.fallback_used is True
    unapproved = resolve_model(
        [highest, replace(lower, approved_for_review=False)],
        verified_available={"lower"},
        allow_fallback=True,
    )
    assert unapproved.status == "BLOCKED"
