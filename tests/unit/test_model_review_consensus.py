from __future__ import annotations

import pytest

from cloud_expert.review.consensus import arbitrate, parse_opinion, validate_manifest

HASH = "a" * 64


def _opinion(verdict: str, **changes: object):
    payload: dict[str, object] = {
        "subject_type": "mapping_candidate",
        "subject_id": 1,
        "input_hash": HASH,
        "verdict": verdict,
        "reason_code": "source_checked",
        "rationale": "Official evidence supports the conclusion.",
        "evidence_ids": [10],
        "conditions": [],
    }
    payload.update(changes)
    return parse_opinion(payload)


def test_dual_model_approval_is_internal_only() -> None:
    result = arbitrate(
        "requires_human_confirmation",
        HASH,
        (10,),
        _opinion("approve_internal"),
        _opinion("approve_internal"),
    )
    assert result.verdict == "approve_internal"
    assert result.reason_code == "dual_model_internal_consensus"


def test_precheck_block_overrides_agreement() -> None:
    result = arbitrate(
        "internal_research_only",
        HASH,
        (10,),
        _opinion("approve_internal"),
        _opinion("approve_internal"),
    )
    assert result.verdict == "defer"
    assert result.reason_code == "precheck_blocked"


def test_adversarial_rejection_prevents_approval() -> None:
    result = arbitrate(
        "requires_human_confirmation", HASH, (10,), _opinion("approve_internal"), _opinion("reject")
    )
    assert result.verdict == "reject"


def test_disagreement_and_stale_input_defer() -> None:
    primary = _opinion("approve_internal")
    adversarial = _opinion("defer")
    assert (
        arbitrate("requires_human_confirmation", HASH, (10,), primary, adversarial).reason_code
        == "model_disagreement"
    )
    assert (
        arbitrate("requires_human_confirmation", "b" * 64, (10,), primary, primary).reason_code
        == "stale_review_input"
    )


def test_conditional_consensus_preserves_both_conditions() -> None:
    first = _opinion("approve_with_conditions", conditions=["condition A"])
    second = _opinion("approve_with_conditions", conditions=["condition B"])
    result = arbitrate("requires_human_confirmation", HASH, (10,), first, second)
    assert result.verdict == "approve_with_conditions"
    assert result.conditions == ("condition A", "condition B")


def test_unknown_evidence_deferred() -> None:
    result = arbitrate(
        "requires_human_confirmation",
        HASH,
        (10,),
        _opinion("approve_internal", evidence_ids=[11]),
        _opinion("approve_internal"),
    )
    assert result.reason_code == "unverified_evidence"


def test_manifest_rejects_missing_identity_and_duplicate_subjects() -> None:
    item = {
        "subject_type": "mapping_candidate",
        "subject_id": 1,
        "input_hash": HASH,
        "verdict": "defer",
        "reason_code": "unknown",
        "rationale": "Cannot verify source.",
        "evidence_ids": [],
    }
    manifest = {
        "schema_version": "1.0",
        "stage": "primary",
        "model": "gpt-6-astra",
        "review_session_id": "session-one",
        "items": [item, item],
    }
    with pytest.raises(ValueError, match="duplicate subject"):
        validate_manifest(manifest, "primary")
    manifest["items"] = [item]
    manifest["model"] = "deterministic_evidence_precheck"
    with pytest.raises(ValueError, match="highest-tier"):
        validate_manifest(manifest, "primary")


def test_conditional_approval_requires_conditions() -> None:
    with pytest.raises(ValueError, match="requires conditions"):
        _opinion("approve_with_conditions")
