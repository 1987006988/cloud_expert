"""Pure C02 eligibility evaluation, not approval issuance or a sending service.

Integration: build these attestations from trusted backend validators, never from
UI/client approval flags. Bind panel input_hash to dependency_bundle_hash(request)
and the artifact hash. Load the checked-in policy with load_output_policy; supply
an explicit aware evaluation time. Reevaluate after every dependency change.
No result changes a Gate, persists an approval, authorizes sending or deploys code.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    model_validator,
)

Identifier = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DependencyKind = Literal[
    "controlled_input",
    "precheck",
    "evidence_chain",
    "market",
    "mapping",
    "price",
    "tco",
    "decision",
]
REQUIRED_DEPENDENCIES: tuple[DependencyKind, ...] = (
    "controlled_input",
    "precheck",
    "evidence_chain",
    "market",
    "mapping",
    "price",
    "tco",
    "decision",
)


class EligibilityState(StrEnum):
    INTERNAL_DRAFT = "internal_draft"
    INTERNAL_REVIEWED = "internal_reviewed"
    CUSTOMER_CANDIDATE = "customer_candidate"
    CUSTOMER_APPROVED = "customer_approved"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class OutputScope(Contract):
    market: Literal["domestic", "international", "cross_market_analysis", "unknown"]
    country: str | None = None
    region: str | None = None
    provider_partitions: tuple[str, ...] = ()
    scenario_id: Identifier
    purpose: Identifier
    claims: tuple[Identifier, ...] = ()

    def covers(self, requested: OutputScope) -> bool:
        return (
            self.market == requested.market
            and self.country == requested.country
            and self.region == requested.region
            and set(self.provider_partitions) == set(requested.provider_partitions)
            and self.scenario_id == requested.scenario_id
            and self.purpose == requested.purpose
            and bool(requested.claims)
            and set(requested.claims).issubset(self.claims)
        )


class DependencyAttestation(Contract):
    kind: DependencyKind
    status: Literal["passed", "missing", "partial", "failed", "expired", "unknown"]
    record_id: Identifier
    current_version: Identifier
    checked_version: Identifier
    current_hash: Digest
    checked_hash: Digest
    scope: OutputScope
    checked_at: AwareDatetime
    valid_until: AwareDatetime
    conditions_satisfied: StrictBool = False
    evidence_ids: tuple[Annotated[int, Field(strict=True, gt=0)], ...] = ()
    source_document_ids: tuple[Annotated[int, Field(strict=True, gt=0)], ...] = ()
    snapshot_hashes: tuple[Digest, ...] = ()
    official_sources_verified: StrictBool = False


class ModelOpinion(Contract):
    authority: Literal["model"] = "model"
    model_id: Identifier
    model_version: Identifier
    session_id: Identifier
    audit_record_id: Identifier
    verdict: Literal[
        "approved", "conditional", "reject", "defer", "reparse_required", "insufficient_evidence"
    ]
    artifact_hash: Digest
    input_hash: Digest
    scope: OutputScope
    reviewed_at: AwareDatetime
    valid_until: AwareDatetime
    runtime_identity_verified: StrictBool = False
    immutable_version_pinned: StrictBool = False
    internal_rc_audit_verified: StrictBool = False
    structured_output_valid: StrictBool = False
    conditions_satisfied: StrictBool = False
    evidence_ids: tuple[Annotated[int, Field(strict=True, gt=0)], ...] = ()


class ModelPanel(Contract):
    generation_session_id: Identifier
    primary: ModelOpinion
    adversarial: ModelOpinion
    adversarial_agrees: StrictBool
    arbitration: ModelOpinion | None = None


class ControlledContentApproval(Contract):
    """Existing audited model writeback; not a new approval or owner send grant."""

    authority: Literal["model"]
    record_id: Identifier
    audit_event_id: Identifier
    review_state: Literal["model_approved", "model_approved_with_conditions"]
    policy_version: Identifier
    panel_session_ids: tuple[Identifier, ...]
    controlled_writeback_verified: StrictBool = False
    conditions_enforced: StrictBool = False
    artifact_hash: Digest
    input_hash: Digest
    scope: OutputScope
    applied_at: AwareDatetime
    valid_until: AwareDatetime


class OutputEligibilityInput(Contract):
    artifact_id: Identifier
    artifact_hash: Digest
    scope: OutputScope
    dependencies: tuple[DependencyAttestation, ...] = ()
    panel: ModelPanel | None = None
    customer_content_approval: ControlledContentApproval | None = None


class OutputEligibilityPolicy(Contract):
    policy_version: Literal["c02.output_eligibility.v1"] = "c02.output_eligibility.v1"
    review_authority: Literal["model_not_human"] = "model_not_human"
    required_model_id: Identifier = "gpt-6-astra"
    required_dependencies: tuple[DependencyKind, ...] = REQUIRED_DEPENDENCIES
    internal_rc_alias_scope: Literal["internal_only"] = "internal_only"
    customer_content_approval: Literal["controlled_independent_model_record"] = (
        "controlled_independent_model_record"
    )
    owner_external_send_authorization: Literal["not_granted"] = "not_granted"
    production_authorization: Literal["not_granted"] = "not_granted"

    @model_validator(mode="after")
    def fixed_requirements(self) -> OutputEligibilityPolicy:
        if len(self.required_dependencies) != len(REQUIRED_DEPENDENCIES) or set(
            self.required_dependencies
        ) != set(REQUIRED_DEPENDENCIES):
            raise ValueError("all mandatory dependencies are required exactly once")
        return self


class OutputEligibilityResult(Contract):
    state: EligibilityState
    policy_version: str
    artifact_id: str
    artifact_hash: str
    dependency_bundle_hash: str
    internal_review_blockers: tuple[str, ...]
    customer_candidate_blockers: tuple[str, ...]
    customer_approval_blockers: tuple[str, ...]
    external_send_allowed: Literal[False] = False
    external_send_blockers: tuple[str, ...] = ("owner_external_send_authorization_not_granted",)
    production_authorized: Literal[False] = False
    review_authority: Literal["model"] = "model"
    human_review_claimed: Literal[False] = False
    policy_fingerprint: str


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_output_policy(path: Path) -> OutputEligibilityPolicy:
    return OutputEligibilityPolicy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def dependency_bundle_hash(request: OutputEligibilityInput) -> str:
    dependencies = [d.model_dump(mode="json") for d in request.dependencies]
    dependencies.sort(key=lambda d: (d["kind"], d["record_id"]))
    return _hash(
        {
            "artifact_id": request.artifact_id,
            "artifact_hash": request.artifact_hash,
            "scope": request.scope.model_dump(mode="json"),
            "dependencies": dependencies,
        }
    )


def _valid_window(start: datetime, end: datetime, now: datetime) -> bool:
    return start <= now < end


def _known(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"unknown", "unspecified", "n/a", "*"})


def _panel_blockers(
    request: OutputEligibilityInput,
    policy: OutputEligibilityPolicy,
    bundle_hash: str,
    now: datetime,
) -> tuple[list[str], list[str]]:
    internal: list[str] = []
    customer: list[str] = []
    panel = request.panel
    if panel is None:
        return ["model_panel_missing"], []
    stages = [("primary", panel.primary), ("adversarial", panel.adversarial)]
    if (
        not panel.adversarial_agrees or panel.primary.verdict != panel.adversarial.verdict
    ) and panel.arbitration is None:
        internal.append("model_panel_unresolved_disagreement")
    if panel.arbitration is not None:
        stages.append(("arbitration", panel.arbitration))
    sessions = [panel.generation_session_id] + [op.session_id for _, op in stages]
    if len(set(sessions)) != len(sessions):
        internal.append("model_panel_sessions_not_independent")
    if len({op.audit_record_id for _, op in stages}) != len(stages):
        internal.append("model_panel_audit_records_not_independent")
    allowed_evidence = {eid for dep in request.dependencies for eid in dep.evidence_ids}
    for name, op in stages:
        prefix = f"model_panel.{name}"
        if op.model_id != policy.required_model_id or not op.runtime_identity_verified:
            internal.append(prefix + ".model_identity_unverified")
        pinned = op.immutable_version_pinned and op.model_version not in {
            "alias_unresolved",
            "unknown",
        }
        if not pinned:
            customer.append(prefix + ".customer_model_version_unverified")
            if not op.internal_rc_audit_verified:
                internal.append(prefix + ".reproducibility_unverified")
        if op.verdict not in {"approved", "conditional"}:
            internal.append(prefix + ".nonapproval")
        if not op.structured_output_valid or not op.conditions_satisfied:
            internal.append(prefix + ".unmet_review_conditions")
        if op.artifact_hash != request.artifact_hash or op.input_hash != bundle_hash:
            internal.append(prefix + ".stale_input")
        if not op.scope.covers(request.scope):
            internal.append(prefix + ".scope_exceeded")
        if not _valid_window(op.reviewed_at, op.valid_until, now):
            internal.append(prefix + ".expired_or_future_review")
        if any(dep.checked_at > op.reviewed_at for dep in request.dependencies):
            internal.append(prefix + ".review_predates_dependency_check")
        if not op.evidence_ids or not set(op.evidence_ids).issubset(allowed_evidence):
            internal.append(prefix + ".unsupported_citations")
    return internal, customer


def evaluate_output_eligibility(
    request: OutputEligibilityInput, *, policy: OutputEligibilityPolicy, now: datetime
) -> OutputEligibilityResult:
    """Evaluate trusted attestations; fail closed and return reasons, without side effects."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evaluation time must be timezone-aware")
    bundle_hash = dependency_bundle_hash(request)
    internal, customer = _panel_blockers(request, policy, bundle_hash, now)
    scope = request.scope
    if scope.market not in {"domestic", "international"}:
        customer.append("market_unknown_or_cross_market_research")
    if (
        not _known(scope.country)
        or len(scope.country or "") != 2
        or not (scope.country or "").isalpha()
        or not (scope.country or "").isupper()
        or scope.country == "ZZ"
    ):
        customer.append("country_unverified")
    if (
        not _known(scope.region)
        or not scope.provider_partitions
        or not all(map(_known, scope.provider_partitions))
    ):
        customer.append("region_or_partition_unverified")
    if not scope.claims:
        customer.append("claim_scope_missing")
    for kind in policy.required_dependencies:
        matches = [dep for dep in request.dependencies if dep.kind == kind]
        blockers: list[str] = []
        if len(matches) != 1:
            blockers.append(f"{kind}.missing_or_duplicate_attestation")
        for dep in matches:
            if dep.status != "passed":
                blockers.append(f"{kind}.{dep.status}")
            if dep.current_version != dep.checked_version or dep.current_hash != dep.checked_hash:
                blockers.append(f"{kind}.stale_version")
            if not _valid_window(dep.checked_at, dep.valid_until, now):
                blockers.append(f"{kind}.expired_or_future_check")
            if not dep.conditions_satisfied:
                blockers.append(f"{kind}.unmet_conditions")
            if not dep.scope.covers(scope):
                blockers.append(f"{kind}.scope_exceeded")
            if kind in {"evidence_chain", "price"} and not (
                dep.official_sources_verified
                and dep.evidence_ids
                and dep.source_document_ids
                and dep.snapshot_hashes
            ):
                blockers.append(f"{kind}.official_evidence_missing")
        customer.extend(blockers)
        if kind in {"controlled_input", "precheck", "evidence_chain"}:
            internal.extend(blockers)
    customer.extend(internal)
    state = EligibilityState.INTERNAL_DRAFT if internal else EligibilityState.INTERNAL_REVIEWED
    approval_blockers: list[str] = []
    grant = request.customer_content_approval
    panel_sessions = []
    panel_review_times = []
    if request.panel is not None:
        panel_sessions = [request.panel.primary.session_id, request.panel.adversarial.session_id]
        panel_review_times = [
            request.panel.primary.reviewed_at,
            request.panel.adversarial.reviewed_at,
        ]
        if request.panel.arbitration is not None:
            panel_sessions.append(request.panel.arbitration.session_id)
            panel_review_times.append(request.panel.arbitration.reviewed_at)
    if customer:
        approval_blockers.append("customer_candidate_requirements_unmet")
    else:
        state = EligibilityState.CUSTOMER_CANDIDATE
    if grant is None:
        approval_blockers.append("controlled_model_content_approval_missing")
    elif (
        not grant.controlled_writeback_verified
        or not grant.conditions_enforced
        or grant.policy_version != policy.policy_version
        or sorted(grant.panel_session_ids) != sorted(panel_sessions)
        or grant.artifact_hash != request.artifact_hash
        or grant.input_hash != bundle_hash
        or not grant.scope.covers(scope)
        or any(reviewed_at > grant.applied_at for reviewed_at in panel_review_times)
        or not _valid_window(grant.applied_at, grant.valid_until, now)
    ):
        approval_blockers.append("model_content_approval_invalid_stale_or_out_of_scope")
    if not approval_blockers:
        state = EligibilityState.CUSTOMER_APPROVED
    return OutputEligibilityResult(
        state=state,
        policy_version=policy.policy_version,
        artifact_id=request.artifact_id,
        artifact_hash=request.artifact_hash,
        dependency_bundle_hash=bundle_hash,
        internal_review_blockers=tuple(sorted(set(internal))),
        customer_candidate_blockers=tuple(sorted(set(customer))),
        customer_approval_blockers=tuple(sorted(set(approval_blockers))),
        policy_fingerprint=_hash(policy.model_dump(mode="json")),
    )
