"""Synthetic attestations only; no real product or customer authorization is created."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from cloud_expert.model_review.output_policy import (
    REQUIRED_DEPENDENCIES,
    ControlledContentApproval,
    DependencyAttestation,
    EligibilityState,
    ModelOpinion,
    ModelPanel,
    OutputEligibilityInput,
    OutputEligibilityPolicy,
    OutputScope,
    dependency_bundle_hash,
    evaluate_output_eligibility,
    load_output_policy,
)

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
START = NOW - timedelta(hours=1)
END = NOW + timedelta(hours=1)
POLICY = OutputEligibilityPolicy()


def scope(**changes):
    return OutputScope.model_validate(
        {
            "market": "domestic",
            "country": "CN",
            "region": "synthetic-region",
            "provider_partitions": ("synthetic-provider:synthetic-cn",),
            "scenario_id": "synthetic-scenario",
            "purpose": "synthetic-comparison",
            "claims": ("product_category", "price"),
            **changes,
        }
    )


def with_panel(request, **opinion_changes):
    opinion = {
        "model_id": POLICY.required_model_id,
        "model_version": "synthetic-pinned-version",
        "session_id": "synthetic-primary",
        "audit_record_id": "synthetic-audit-primary",
        "verdict": "approved",
        "artifact_hash": request.artifact_hash,
        "input_hash": dependency_bundle_hash(request),
        "scope": request.scope,
        "reviewed_at": START,
        "valid_until": END,
        "runtime_identity_verified": True,
        "immutable_version_pinned": True,
        "structured_output_valid": True,
        "conditions_satisfied": True,
        "evidence_ids": (1,),
        **opinion_changes,
    }
    primary = ModelOpinion.model_validate(opinion)
    adversarial = ModelOpinion.model_validate(
        {
            **opinion,
            "session_id": "synthetic-adversarial",
            "audit_record_id": "synthetic-audit-adversarial",
        }
    )
    panel = ModelPanel(
        generation_session_id="synthetic-generator",
        primary=primary,
        adversarial=adversarial,
        adversarial_agrees=True,
    )
    return request.model_copy(update={"panel": panel})


def ready():
    deps = tuple(
        DependencyAttestation(
            kind=kind,
            status="passed",
            record_id=f"synthetic-{kind}",
            current_version="v1",
            checked_version="v1",
            current_hash="b" * 64,
            checked_hash="b" * 64,
            scope=scope(),
            checked_at=START,
            valid_until=END,
            conditions_satisfied=True,
            evidence_ids=(1,),
            source_document_ids=(1,),
            snapshot_hashes=("c" * 64,),
            official_sources_verified=True,
        )
        for kind in REQUIRED_DEPENDENCIES
    )
    return with_panel(
        OutputEligibilityInput(
            artifact_id="synthetic-artifact",
            artifact_hash="a" * 64,
            scope=scope(),
            dependencies=deps,
        )
    )


def evaluate(request):
    return evaluate_output_eligibility(request, policy=POLICY, now=NOW)


def change_dep(request, kind, **changes):
    deps = tuple(
        dep.model_copy(update=changes) if dep.kind == kind else dep for dep in request.dependencies
    )
    return with_panel(request.model_copy(update={"dependencies": deps}))


def with_approval(request, **changes):
    panel = request.panel
    sessions = (panel.primary.session_id, panel.adversarial.session_id)
    if panel.arbitration:
        sessions += (panel.arbitration.session_id,)
    approval = ControlledContentApproval.model_validate(
        {
            "authority": "model",
            "record_id": "synthetic-writeback",
            "audit_event_id": "synthetic-event",
            "review_state": "model_approved",
            "policy_version": POLICY.policy_version,
            "panel_session_ids": sessions,
            "controlled_writeback_verified": True,
            "conditions_enforced": True,
            "artifact_hash": request.artifact_hash,
            "input_hash": dependency_bundle_hash(request),
            "scope": request.scope,
            "applied_at": NOW,
            "valid_until": END,
            **changes,
        }
    )
    return request.model_copy(update={"customer_content_approval": approval})


def test_checked_in_policy_is_strict_and_does_not_grant_send_or_production():
    path = (
        Path(__file__).resolve().parents[2] / "config/model_review/output_eligibility_policy.yaml"
    )
    assert load_output_policy(path) == POLICY
    with pytest.raises(ValidationError):
        OutputEligibilityPolicy(required_dependencies=("precheck",))
    for key in ("owner_external_send_authorization", "production_authorization"):
        with pytest.raises(ValidationError):
            OutputEligibilityPolicy.model_validate({key: "granted"})


def test_four_states_do_not_imply_sending_and_never_claim_human_review():
    request = ready()
    draft = evaluate(request.model_copy(update={"panel": None}))
    internal = evaluate(change_dep(request, "price", status="partial"))
    candidate = evaluate(request)
    approved = evaluate(with_approval(request))
    assert [r.state for r in (draft, internal, candidate, approved)] == list(EligibilityState)
    assert candidate.customer_approval_blockers == ("controlled_model_content_approval_missing",)
    for result in (draft, internal, candidate, approved):
        assert not result.external_send_allowed and not result.production_authorized
        assert result.external_send_blockers == ("owner_external_send_authorization_not_granted",)
        assert result.review_authority == "model" and result.human_review_claimed is False


@pytest.mark.parametrize("kind", REQUIRED_DEPENDENCIES)
@pytest.mark.parametrize("status", ["missing", "partial", "failed", "expired", "unknown"])
def test_every_nonpassing_dependency_blocks_candidate_even_with_model_receipt(kind, status):
    request = change_dep(ready(), kind, status=status)
    result = evaluate(with_approval(request))
    assert result.state not in {
        EligibilityState.CUSTOMER_CANDIDATE,
        EligibilityState.CUSTOMER_APPROVED,
    }
    assert f"{kind}.{status}" in result.customer_candidate_blockers


@pytest.mark.parametrize("kind", REQUIRED_DEPENDENCIES)
def test_missing_and_duplicate_dependency_attestations_fail_closed(kind):
    request = ready()
    missing = with_panel(
        request.model_copy(
            update={"dependencies": tuple(d for d in request.dependencies if d.kind != kind)}
        )
    )
    duplicate = with_panel(
        request.model_copy(
            update={
                "dependencies": (
                    *request.dependencies,
                    next(d for d in request.dependencies if d.kind == kind),
                )
            }
        )
    )
    for changed in (missing, duplicate):
        assert (
            f"{kind}.missing_or_duplicate_attestation"
            in evaluate(changed).customer_candidate_blockers
        )


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"current_version": "v2"}, "stale_version"),
        ({"current_hash": "d" * 64}, "stale_version"),
        ({"valid_until": NOW}, "expired_or_future_check"),
        ({"checked_at": END}, "expired_or_future_check"),
        ({"conditions_satisfied": False}, "unmet_conditions"),
        ({"scope": scope(region="another-synthetic-region")}, "scope_exceeded"),
        ({"scope": scope(claims=("product_category",))}, "scope_exceeded"),
    ],
)
def test_version_time_conditions_and_narrow_mapping_cannot_support_broader_claims(changes, reason):
    assert (
        f"mapping.{reason}"
        in evaluate(change_dep(ready(), "mapping", **changes)).customer_candidate_blockers
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"market": "unknown"},
        {"market": "cross_market_analysis"},
        {"market": "international", "country": None},
        {"country": "ZZ"},
        {"country": "unknown"},
        {"region": None},
        {"region": "unknown"},
        {"provider_partitions": ()},
        {"provider_partitions": ("unknown",)},
        {"claims": ()},
    ],
)
def test_unknown_or_cross_market_scope_is_not_customer_ready(changes):
    request = ready().model_copy(update={"scope": scope(**changes)})
    request = with_panel(
        request.model_copy(
            update={
                "dependencies": tuple(
                    d.model_copy(update={"scope": request.scope}) for d in request.dependencies
                )
            }
        )
    )
    assert evaluate(request).customer_candidate_blockers
    assert evaluate(request).state != EligibilityState.CUSTOMER_CANDIDATE


@pytest.mark.parametrize("kind", ["evidence_chain", "price"])
@pytest.mark.parametrize(
    "missing",
    ["evidence_ids", "source_document_ids", "snapshot_hashes", "official_sources_verified"],
)
def test_passed_label_alone_does_not_establish_official_evidence(kind, missing):
    value = False if missing == "official_sources_verified" else ()
    result = evaluate(change_dep(ready(), kind, **{missing: value}))
    assert f"{kind}.official_evidence_missing" in result.customer_candidate_blockers


@pytest.mark.parametrize(
    "changes, suffix",
    [
        ({"runtime_identity_verified": False}, "model_identity_unverified"),
        ({"model_id": "synthetic-weaker-model"}, "model_identity_unverified"),
        ({"input_hash": "f" * 64}, "stale_input"),
        ({"artifact_hash": "f" * 64}, "stale_input"),
        ({"verdict": "reject"}, "nonapproval"),
        ({"verdict": "defer"}, "nonapproval"),
        ({"verdict": "insufficient_evidence"}, "nonapproval"),
        ({"structured_output_valid": False}, "unmet_review_conditions"),
        ({"conditions_satisfied": False}, "unmet_review_conditions"),
        ({"valid_until": NOW}, "expired_or_future_review"),
        ({"scope": scope(claims=("product_category",))}, "scope_exceeded"),
        ({"evidence_ids": (999,)}, "unsupported_citations"),
    ],
)
def test_model_panel_is_bound_independent_current_and_evidence_limited(changes, suffix):
    result = evaluate(with_panel(ready(), **changes))
    assert result.state == EligibilityState.INTERNAL_DRAFT
    assert f"model_panel.primary.{suffix}" in result.internal_review_blockers


def test_sessions_include_generator_and_arbitrator_and_disagreement_requires_arbitration():
    request = ready()
    panel = request.panel
    same_session = panel.model_copy(update={"generation_session_id": panel.primary.session_id})
    assert (
        "model_panel_sessions_not_independent"
        in evaluate(request.model_copy(update={"panel": same_session})).internal_review_blockers
    )
    disagree = panel.model_copy(update={"adversarial_agrees": False})
    assert (
        "model_panel_unresolved_disagreement"
        in evaluate(request.model_copy(update={"panel": disagree})).internal_review_blockers
    )
    arbitration = panel.primary.model_copy(
        update={
            "session_id": "synthetic-arbitrator",
            "audit_record_id": "synthetic-audit-arbitrator",
        }
    )
    resolved = disagree.model_copy(update={"arbitration": arbitration})
    assert (
        evaluate(request.model_copy(update={"panel": resolved})).state
        == EligibilityState.CUSTOMER_CANDIDATE
    )
    rejection = resolved.model_copy(
        update={"adversarial": panel.adversarial.model_copy(update={"verdict": "reject"})}
    )
    assert (
        evaluate(request.model_copy(update={"panel": rejection})).state
        == EligibilityState.INTERNAL_DRAFT
    )


def test_alias_rc_policy_only_affects_internal_audit_not_facts_or_customer_qualification():
    request = with_panel(
        ready(),
        immutable_version_pinned=False,
        model_version="alias_unresolved",
        internal_rc_audit_verified=True,
    )
    result = evaluate(request)
    assert result.state == EligibilityState.INTERNAL_REVIEWED
    assert (
        "model_panel.primary.customer_model_version_unverified"
        in result.customer_candidate_blockers
    )
    broken = change_dep(request, "price", status="partial")
    broken = with_panel(
        broken,
        immutable_version_pinned=False,
        model_version="alias_unresolved",
        internal_rc_audit_verified=True,
    )
    assert "price.partial" in evaluate(broken).customer_candidate_blockers
    unaudited = with_panel(
        request, immutable_version_pinned=False, model_version="alias_unresolved"
    )
    assert evaluate(unaudited).state == EligibilityState.INTERNAL_DRAFT


@pytest.mark.parametrize(
    "changes",
    [
        {"controlled_writeback_verified": False},
        {"conditions_enforced": False},
        {"input_hash": "e" * 64},
        {"artifact_hash": "e" * 64},
        {"panel_session_ids": ("unrelated-session",)},
        {"policy_version": "old-policy"},
        {"scope": scope(purpose="different-purpose")},
        {"valid_until": NOW},
    ],
)
def test_invalid_content_receipt_never_marks_customer_approved(changes):
    result = evaluate(with_approval(ready(), **changes))
    assert result.state == EligibilityState.CUSTOMER_CANDIDATE
    assert result.customer_approval_blockers == (
        "model_content_approval_invalid_stale_or_out_of_scope",
    )


def test_strict_input_boundary_and_deterministic_time():
    request = ready()
    assert evaluate(request) == evaluate(request)
    assert evaluate(request).policy_fingerprint
    reversed_request = request.model_copy(
        update={"dependencies": tuple(reversed(request.dependencies))}
    )
    assert dependency_bundle_hash(reversed_request) == dependency_bundle_hash(request)
    assert evaluate(reversed_request) == evaluate(request)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_output_eligibility(request, policy=POLICY, now=NOW.replace(tzinfo=None))
    for change in (
        {"authority": "human"},
        {"runtime_identity_verified": "true"},
        {"customer_eligible": True},
    ):
        with pytest.raises(ValidationError):
            ModelOpinion.model_validate({**request.panel.primary.model_dump(), **change})
    with pytest.raises(ValidationError):
        OutputEligibilityInput.model_validate({**request.model_dump(), "send_authorized": True})


def test_conditional_panel_requires_enforced_conditions_and_changed_input_invalidates_receipt():
    request = with_panel(ready(), verdict="conditional")
    assert evaluate(request).state == EligibilityState.CUSTOMER_CANDIDATE
    approved = with_approval(request)
    changed = change_dep(approved, "tco", current_hash="f" * 64, checked_hash="f" * 64)
    result = evaluate(changed)
    assert result.state == EligibilityState.CUSTOMER_CANDIDATE
    assert (
        "model_content_approval_invalid_stale_or_out_of_scope" in result.customer_approval_blockers
    )


def test_distinct_sessions_cannot_reuse_one_audit_record():
    request = ready()
    panel = request.panel
    repeated = panel.adversarial.model_copy(
        update={"audit_record_id": panel.primary.audit_record_id}
    )
    request = request.model_copy(
        update={"panel": panel.model_copy(update={"adversarial": repeated})}
    )
    assert "model_panel_audit_records_not_independent" in evaluate(request).internal_review_blockers


def test_receipt_and_review_cannot_predate_their_dependencies():
    request = ready()
    too_early = with_panel(request, reviewed_at=START - timedelta(seconds=1))
    assert (
        "model_panel.primary.review_predates_dependency_check"
        in evaluate(too_early).internal_review_blockers
    )
    early_receipt = with_approval(request, applied_at=START - timedelta(seconds=1))
    assert evaluate(early_receipt).state == EligibilityState.CUSTOMER_CANDIDATE


def test_rejected_model_record_and_human_label_are_not_content_approvals():
    for change in ({"review_state": "model_rejected_reparse"}, {"authority": "human"}):
        with pytest.raises(ValidationError):
            with_approval(ready(), **change)


def test_unmet_conditional_review_never_advances():
    result = evaluate(with_panel(ready(), verdict="conditional", conditions_satisfied=False))
    assert result.state == EligibilityState.INTERNAL_DRAFT


def test_alias_claimed_pinned_still_does_not_satisfy_customer_audit():
    request = with_panel(
        ready(),
        model_version="alias_unresolved",
        immutable_version_pinned=True,
        internal_rc_audit_verified=True,
    )
    assert evaluate(with_approval(request)).state == EligibilityState.INTERNAL_REVIEWED
