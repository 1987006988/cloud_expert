"""Append-only policy replacement of an unchanged complete catalog SKU tier group.

No prices, vendor dates, existing review rows, or Gates are changed. A trusted,
read-only adapter MUST re-extract/verify catalog bytes, policy applicability,
license admission and freshness on each callback. This module verifies its typed
bindings against stored rows; a hash is not authorization or an approval.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence

VERSION = "price_replacement_lifecycle_v1"
ACTOR = "deterministic_price_lifecycle"
EVENT_SOURCE = "deterministic_price_supersession"
RUN_PREFIX = "PRICE-REPLACE-"
TARGET = "price_snapshot"

type ID = Annotated[int, Field(strict=True, gt=0)]
type SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
type Label = Annotated[str, Field(min_length=1, max_length=256)]
type Amount = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=8)]
type Purpose = Literal["historical", "current"]


class LifecycleConflict(ValueError):
    """Fail-closed reason code; caller must not approve or consume on failure."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceBinding(_Record):
    evidence_id: ID
    state_sha256: SHA


class VerifiedRate(_Record):
    price_id: ID
    row_sha256: SHA
    rate_code: Label
    locator: Label
    raw_unit: Label
    unit_price: Amount
    minimum_quantity: Amount
    maximum_quantity: Amount | None


class VerifiedPriceGroup(_Record):
    """Adapter proof, not a cached approval.

    The callback discovers the WHOLE group containing requested IDs. For planning,
    the caller must supply that complete group explicitly. dependency_sha256 binds
    raw/manifest/registry/license hashes, claim applicability, and adapter rules.
    Historical mode still verifies the original authorized catalog facts, but must
    not treat withdrawn historical policy as current admissible evidence.
    """

    schema_version: Literal["verified_price_group_v1"] = "verified_price_group_v1"
    verifier_version: Label
    purpose: Purpose
    checked_at: datetime
    price_sku_id: ID
    catalog_snapshot_id: ID
    catalog_sha256: SHA
    catalog_sku: Label
    offer_code: Label
    catalog_scope_sha256: SHA
    catalog_rate_codes: tuple[Label, ...] = Field(min_length=1)
    complete_tier_group: Literal[True]
    authorized_catalog: Literal[True]
    current_policy_verified: bool = Field(strict=True)
    dependency_sha256: SHA
    policy_evidence: tuple[EvidenceBinding, ...]
    rates: tuple[VerifiedRate, ...] = Field(min_length=1)


class ProofVerifier(Protocol):
    def __call__(
        self, session: Session, price_ids: tuple[int, ...], *, purpose: Purpose, now: datetime
    ) -> VerifiedPriceGroup: ...


class ReplacementPlan(_Record):
    schema_version: Literal["price_replacement_plan_v1"] = "price_replacement_plan_v1"
    old: VerifiedPriceGroup
    new: VerifiedPriceGroup
    expected_lifecycle_sha256: SHA
    plan_sha256: SHA


class ReplacementReceipt(_Record):
    schema_version: Literal["price_replacement_receipt_v1"] = "price_replacement_receipt_v1"
    plan: ReplacementPlan
    applied_at: datetime
    receipt_sha256: SHA


class PriceDisposition(_Record):
    price_id: int
    status: Literal["current", "superseded", "blocked"]
    successor_id: int | None = None
    current_price_id: int | None = None
    replacement_path: tuple[int, ...] = ()
    receipt_sha256s: tuple[str, ...] = ()
    proof_sha256: str | None = None
    diagnostics: tuple[str, ...] = ()
    customer_eligible: Literal[False] = False


class ReplacementResult(_Record):
    plan_sha256: str
    receipt_sha256: str | None
    applied: bool
    created: bool
    replaced_prices: int
    transaction_committed: Literal[False] = False
    approvals_granted: Literal[0] = 0


def _require(condition: object, code: str) -> None:
    if not condition:
        raise LifecycleConflict(code)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    _require(value.tzinfo is not None, "aware_time_required")
    return _utc(value)


def _json(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _hash(value: Any) -> str:
    raw = json.dumps(_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _row(row: Any) -> dict[str, Any]:
    return {column.name: _json(getattr(row, column.name)) for column in row.__table__.columns}


def _clean(session: Session) -> None:
    _require(not (session.new or session.dirty or session.deleted), "clean_session_required")


def _price(session: Session, price_id: int) -> PriceSnapshot:
    _require(type(price_id) is int and price_id > 0, "invalid_price_id")
    row = session.get(PriceSnapshot, price_id)
    _require(row is not None, "price_missing")
    assert row is not None
    return row


def evidence_fingerprint(session: Session, evidence_id: int) -> str:
    """Binding helper for adapters; does not verify raw bytes or source permission."""
    with session.no_autoflush:
        row = session.get(Evidence, evidence_id)
        _require(row is not None and row.snapshot_record_id is not None, "evidence_missing")
        assert row is not None
        snapshot = session.get(SnapshotRecord, row.snapshot_record_id)
        _require(snapshot is not None and row.source_document is not None, "snapshot_missing")
        assert snapshot is not None
        _require(
            snapshot.source_document_id == row.source_document_id, "evidence_snapshot_mismatch"
        )
        return _hash([_row(row), _row(row.source_document), _row(snapshot)])


def price_fingerprint(session: Session, price_id: int) -> str:
    """CAS binding over persisted price and ownership metadata, never an approval."""
    with session.no_autoflush:
        row = _price(session, price_id)
        sku = row.price_sku
        _require(sku is not None and sku.region is not None, "price_scope_missing")
        _require(sku.product is not None and sku.provider is not None, "price_owner_missing")
        partition = sku.region.cloud_partition
        _require(partition is not None, "price_partition_missing")
        return _hash(
            [
                _row(row),
                _row(sku),
                _row(sku.region),
                _row(partition),
                _row(sku.product),
                _row(sku.provider),
                evidence_fingerprint(session, row.evidence_id),
            ]
        )


def _proof_state(proof: VerifiedPriceGroup) -> dict[str, Any]:
    # Time must be fresh on every invocation, but does not itself change the facts.
    return proof.model_dump(mode="json", exclude={"checked_at"})


def _ids(proof: VerifiedPriceGroup) -> tuple[int, ...]:
    return tuple(sorted(rate.price_id for rate in proof.rates))


def _verify(
    session: Session, ids: tuple[int, ...], verifier: ProofVerifier, purpose: Purpose, now: datetime
) -> VerifiedPriceGroup:
    _require(callable(verifier), "proof_verifier_required")
    try:
        result = verifier(session, ids, purpose=purpose, now=now)
        _require(type(result) is VerifiedPriceGroup, "unsupported_proof")
        proof = VerifiedPriceGroup.model_validate(result.model_dump(mode="python"))
    except LifecycleConflict:
        raise
    except Exception as exc:
        raise LifecycleConflict("proof_verifier_failed") from exc
    _clean(session)
    _require(
        proof.checked_at.tzinfo is not None
        and _utc(proof.checked_at) == now
        and proof.purpose == purpose,
        "proof_not_fresh_or_wrong_purpose",
    )
    _require(len(set(_ids(proof))) == len(proof.rates), "duplicate_price_in_proof")
    _require(set(ids).issubset(_ids(proof)), "proof_omits_requested_price")
    codes = [rate.rate_code for rate in proof.rates]
    _require(
        len(set(codes)) == len(codes) == len(set(proof.catalog_rate_codes))
        and len(proof.catalog_rate_codes) == len(codes)
        and set(codes) == set(proof.catalog_rate_codes),
        "incomplete_catalog_tier_group",
    )
    _require(
        purpose != "current" or (proof.current_policy_verified and proof.policy_evidence),
        "current_policy_not_verified",
    )
    _require(
        len({item.evidence_id for item in proof.policy_evidence}) == len(proof.policy_evidence),
        "duplicate_policy_binding",
    )
    for binding in proof.policy_evidence:
        _require(
            evidence_fingerprint(session, binding.evidence_id) == binding.state_sha256,
            "policy_binding_changed",
        )
        policy = session.get(Evidence, binding.evidence_id)
        _require(
            purpose != "current" or (policy is not None and policy.review_status != "rejected"),
            "policy_rejected",
        )
    snapshot = session.get(SnapshotRecord, proof.catalog_snapshot_id)
    _require(
        snapshot is not None and snapshot.content_hash == proof.catalog_sha256,
        "catalog_binding_changed",
    )
    ordered = sorted(proof.rates, key=lambda rate: rate.minimum_quantity)
    _require(
        ordered[0].minimum_quantity == 0 and ordered[-1].maximum_quantity is None,
        "incomplete_tier_interval",
    )
    for index, rate in enumerate(ordered):
        _require(
            rate.maximum_quantity is None or rate.maximum_quantity > rate.minimum_quantity,
            "invalid_tier_interval",
        )
        if index:
            _require(
                ordered[index - 1].maximum_quantity == rate.minimum_quantity, "tier_gap_or_overlap"
            )
        row = _price(session, rate.price_id)
        _require(row.price_sku_id == proof.price_sku_id, "mixed_sku_group")
        _require(price_fingerprint(session, row.id) == rate.row_sha256, "price_binding_changed")
        _require(
            row.unit_price == rate.unit_price
            and row.minimum_quantity == rate.minimum_quantity
            and row.maximum_quantity == rate.maximum_quantity,
            "catalog_numeric_mismatch",
        )
        ev, sku = row.evidence, row.price_sku
        partition = sku.region.cloud_partition
        _require(partition is not None, "price_partition_missing")
        assert partition is not None
        _require(
            ev.snapshot_record_id == proof.catalog_snapshot_id and ev.locator == rate.locator,
            "catalog_rate_locator_mismatch",
        )
        _require(ev.source_document.source_type == "pricing", "price_source_not_pricing")
        _require(
            sku.provider_id
            == sku.product.provider_id
            == sku.region.provider_id
            == ev.source_document.provider_id,
            "provider_scope_mismatch",
        )
        _require(
            sku.product.market_mode == sku.region.market_mode == partition.market_mode
            and partition.provider_id == sku.provider_id
            and ev.source_document.cloud_partition == partition.partition_code,
            "market_scope_mismatch",
        )
    # Stable ordering makes proof equality independent of callback iteration order.
    return proof.model_copy(
        update={
            "rates": tuple(sorted(proof.rates, key=lambda rate: rate.rate_code)),
            "catalog_rate_codes": tuple(sorted(proof.catalog_rate_codes)),
            "policy_evidence": tuple(
                sorted(proof.policy_evidence, key=lambda item: item.evidence_id)
            ),
        }
    )


def _pairs(plan: ReplacementPlan) -> list[tuple[VerifiedRate, VerifiedRate]]:
    new = {rate.rate_code: rate for rate in plan.new.rates}
    _require(set(new) == {rate.rate_code for rate in plan.old.rates}, "replacement_tier_mismatch")
    return [(rate, new[rate.rate_code]) for rate in plan.old.rates]


def _identity(session: Session, old: VerifiedPriceGroup, new: VerifiedPriceGroup) -> None:
    _require(old.purpose == "historical" and new.purpose == "current", "replacement_purpose")
    for key in (
        "verifier_version",
        "price_sku_id",
        "catalog_snapshot_id",
        "catalog_sha256",
        "catalog_sku",
        "offer_code",
        "catalog_scope_sha256",
        "catalog_rate_codes",
    ):
        _require(getattr(old, key) == getattr(new, key), f"replacement_identity_mismatch:{key}")
    _require(not set(_ids(old)) & set(_ids(new)), "self_replacement")
    new_rates = {rate.rate_code: rate for rate in new.rates}
    for before in old.rates:
        after = new_rates[before.rate_code]
        _require(after.price_id > before.price_id, "successor_not_newer")
        for key in ("locator", "raw_unit", "unit_price", "minimum_quantity", "maximum_quantity"):
            _require(
                getattr(before, key) == getattr(after, key), f"replacement_rate_mismatch:{key}"
            )
        a, b = _price(session, before.price_id), _price(session, after.price_id)
        # Same SKU ID pins numeric billing unit, currency, provider, region and tax identity.
        for key in (
            "price_sku_id",
            "unit_price",
            "minimum_quantity",
            "maximum_quantity",
            "billing_period",
            "discount_type",
            "captured_at",
            "effective_from",
            "effective_to",
            "source_payload_path",
        ):
            _require(
                _json(getattr(a, key)) == _json(getattr(b, key)), f"replacement_row_mismatch:{key}"
            )
        _require(a.evidence_id != b.evidence_id, "replacement_evidence_not_new")
        _require(_utc(b.created_at) >= _utc(a.created_at), "successor_creation_precedes_old")


def _plan_hash(plan: ReplacementPlan) -> str:
    return _hash(plan.model_dump(mode="json", exclude={"plan_sha256"}))


def _receipt_hash(receipt: ReplacementReceipt) -> str:
    return _hash(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))


def _binding_ids(plan: ReplacementPlan) -> list[int]:
    return sorted(
        {item.evidence_id for group in (plan.old, plan.new) for item in group.policy_evidence}
    )


def _event_records(receipt: ReplacementReceipt, old_id: int, new_id: int) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "price_replacement_event_v1",
            "receipt_sha256": receipt.receipt_sha256,
            "plan_sha256": receipt.plan.plan_sha256,
            "price_sku_id": receipt.plan.old.price_sku_id,
            "old_price_id": old_id,
            "new_price_id": new_id,
        }
    ]


def _ledger(session: Session) -> list[ReplacementReceipt]:
    """Validate the entire dedicated namespace, including orphan/malformed envelopes."""
    runs = list(
        session.scalars(
            select(ModelReviewRun)
            .where(
                or_(
                    ModelReviewRun.reviewer_model == ACTOR,
                    ModelReviewRun.policy_version == VERSION,
                    ModelReviewRun.run_code.startswith(RUN_PREFIX),
                )
            )
            .order_by(ModelReviewRun.id)
        )
    )
    receipts: list[ReplacementReceipt] = []
    event_ids: set[int] = set()
    edges: dict[int, int] = {}
    incoming: set[int] = set()
    for run in runs:
        try:
            receipt = ReplacementReceipt.model_validate(run.summary_json)
        except ValueError as exc:
            raise LifecycleConflict("malformed_lifecycle_receipt") from exc
        plan = receipt.plan
        _require(
            _plan_hash(plan) == plan.plan_sha256
            and _receipt_hash(receipt) == receipt.receipt_sha256,
            "lifecycle_hash_mismatch",
        )
        _require(
            run.run_code == RUN_PREFIX + plan.plan_sha256
            and run.reviewer_model == ACTOR
            and run.policy_version == VERSION
            and run.input_fingerprint == plan.plan_sha256
            and _utc(run.reviewed_at) == _utc(receipt.applied_at),
            "lifecycle_run_mismatch",
        )
        _identity(session, plan.old, plan.new)
        findings = list(
            session.scalars(select(ModelReviewFinding).where(ModelReviewFinding.run_id == run.id))
        )
        _require(len(findings) == len(plan.old.rates), "lifecycle_group_incomplete")
        by_old = {finding.subject_id: finding for finding in findings}
        _require(set(by_old) == set(_ids(plan.old)), "lifecycle_findings_mismatch")
        for before, after in _pairs(plan):
            _require(before.price_id not in edges, "lifecycle_fork_or_duplicate")
            _require(after.price_id not in incoming, "lifecycle_merge_or_duplicate")
            edges[before.price_id] = after.price_id
            incoming.add(after.price_id)
            finding = by_old[before.price_id]
            bindings = _binding_ids(plan)
            _require(
                finding.subject_type == TARGET
                and finding.verdict == "superseded_by_verified_price"
                and finding.reason_code == VERSION
                and finding.input_hash == plan.plan_sha256
                and finding.evidence_ids == bindings
                and finding.rationale == receipt.receipt_sha256,
                "lifecycle_finding_mismatch",
            )
            assignments = list(
                session.scalars(
                    select(ModelReviewAssignment).where(
                        ModelReviewAssignment.precheck_finding_id == finding.id
                    )
                )
            )
            _require(len(assignments) == 1, "lifecycle_assignment_missing")
            assignment = assignments[0]
            _require(
                assignment.precheck_run_id == run.id
                and assignment.target_type == TARGET
                and assignment.target_id == before.price_id
                and assignment.input_hash == plan.plan_sha256
                and assignment.prior_review_status is None
                and assignment.review_state == "superseded"
                and assignment.evidence_ids == bindings
                and _utc(assignment.created_at) == _utc(receipt.applied_at)
                and _utc(assignment.updated_at) == _utc(receipt.applied_at),
                "lifecycle_assignment_mismatch",
            )
            events = list(
                session.scalars(
                    select(ModelReviewAuditEvent).where(
                        ModelReviewAuditEvent.assignment_id == assignment.id
                    )
                )
            )
            _require(len(events) == 1, "lifecycle_event_missing_or_extra")
            event = events[0]
            event_ids.add(event.id)
            _require(
                event.event_code == f"{RUN_PREFIX}{plan.plan_sha256}:{before.price_id}"
                and event.previous_status is None
                and event.new_status == "superseded"
                and event.source == EVENT_SOURCE
                and event.model_id is None
                and event.reason == VERSION
                and event.downstream_rebuild_required
                and _utc(event.timestamp) == _utc(receipt.applied_at)
                and event.affected_records
                == _event_records(receipt, before.price_id, after.price_id),
                "lifecycle_event_mismatch",
            )
        receipts.append(receipt)
    observed_events = set(
        session.scalars(
            select(ModelReviewAuditEvent.id).where(
                or_(
                    ModelReviewAuditEvent.source == EVENT_SOURCE,
                    ModelReviewAuditEvent.event_code.startswith(RUN_PREFIX),
                )
            )
        )
    )
    _require(observed_events == event_ids, "orphan_lifecycle_event")
    for start in edges:
        seen: set[int] = set()
        at = start
        while at in edges:
            _require(at not in seen, "lifecycle_cycle")
            seen.add(at)
            at = edges[at]
    return receipts


def _for_sku(receipts: list[ReplacementReceipt], sku_id: int) -> list[ReplacementReceipt]:
    return [receipt for receipt in receipts if receipt.plan.old.price_sku_id == sku_id]


def _ledger_hash(receipts: list[ReplacementReceipt]) -> str:
    return _hash(sorted(receipt.receipt_sha256 for receipt in receipts))


def _available(
    old: VerifiedPriceGroup, new: VerifiedPriceGroup, receipts: list[ReplacementReceipt]
) -> None:
    retired = {rate.price_id for receipt in receipts for rate in receipt.plan.old.rates}
    successors = {rate.price_id for receipt in receipts for rate in receipt.plan.new.rates}
    _require(not retired.intersection(_ids(old)), "old_group_already_superseded")
    _require(not (retired | successors).intersection(_ids(new)), "successor_already_in_lifecycle")


def prepare_replacement(
    session: Session,
    old_price_ids: Sequence[int],
    new_price_ids: Sequence[int],
    *,
    verifier: ProofVerifier,
    now: datetime | None = None,
) -> ReplacementPlan:
    """Read-only complete-group plan. Existing old/new prices must already be flushed."""
    _clean(session)
    session.expire_all()
    at = _now(now)
    old_ids, new_ids = tuple(sorted(old_price_ids)), tuple(sorted(new_price_ids))
    _require(
        old_ids
        and new_ids
        and len(set(old_ids)) == len(old_ids)
        and len(set(new_ids)) == len(new_ids),
        "explicit_unique_groups_required",
    )
    with session.no_autoflush:
        old = _verify(session, old_ids, verifier, "historical", at)
        new = _verify(session, new_ids, verifier, "current", at)
        _require(old_ids == _ids(old) and new_ids == _ids(new), "partial_group_request")
        _identity(session, old, new)
        receipts = _for_sku(_ledger(session), old.price_sku_id)
        _available(old, new, receipts)
        plan = ReplacementPlan(
            old=old, new=new, expected_lifecycle_sha256=_ledger_hash(receipts), plan_sha256="0" * 64
        )
        return plan.model_copy(update={"plan_sha256": _plan_hash(plan)})


def _fresh_plan(
    session: Session, plan: ReplacementPlan, verifier: ProofVerifier, now: datetime
) -> None:
    _require(_plan_hash(plan) == plan.plan_sha256, "plan_hash_mismatch")
    for expected, purpose in ((plan.old, "historical"), (plan.new, "current")):
        _require(
            expected.checked_at.tzinfo is not None and _utc(expected.checked_at) <= now,
            "plan_from_future",
        )
        actual = _verify(session, _ids(expected), verifier, purpose, now)  # type: ignore[arg-type]
        _require(_proof_state(actual) == _proof_state(expected), "proof_or_price_changed_replan")
    _identity(session, plan.old, plan.new)


def _append(session: Session, receipt: ReplacementReceipt) -> None:
    plan, at = receipt.plan, receipt.applied_at
    run = ModelReviewRun(
        run_code=RUN_PREFIX + plan.plan_sha256,
        policy_version=VERSION,
        reviewer_model=ACTOR,
        input_fingerprint=plan.plan_sha256,
        reviewed_at=at,
        summary_json=receipt.model_dump(mode="json"),
    )
    session.add(run)
    session.flush()
    for before, after in _pairs(plan):
        finding = ModelReviewFinding(
            run_id=run.id,
            subject_type=TARGET,
            subject_id=before.price_id,
            verdict="superseded_by_verified_price",
            reason_code=VERSION,
            rationale=receipt.receipt_sha256,
            evidence_ids=_binding_ids(plan),
            input_hash=plan.plan_sha256,
        )
        session.add(finding)
        session.flush()
        assignment = ModelReviewAssignment(
            precheck_run_id=run.id,
            precheck_finding_id=finding.id,
            target_type=TARGET,
            target_id=before.price_id,
            input_hash=plan.plan_sha256,
            prior_review_status=None,
            review_state="superseded",
            evidence_ids=_binding_ids(plan),
            created_at=at,
            updated_at=at,
        )
        session.add(assignment)
        session.flush()
        session.add(
            ModelReviewAuditEvent(
                assignment_id=assignment.id,
                event_code=f"{RUN_PREFIX}{plan.plan_sha256}:{before.price_id}",
                previous_status=None,
                new_status="superseded",
                source=EVENT_SOURCE,
                model_id=None,
                reason=VERSION,
                affected_records=_event_records(receipt, before.price_id, after.price_id),
                downstream_rebuild_required=True,
                timestamp=at,
            )
        )
    session.flush()


def apply_replacement(
    session: Session,
    plan: ReplacementPlan,
    *,
    verifier: ProofVerifier,
    apply: bool = False,
    now: datetime | None = None,
) -> ReplacementResult:
    """Default dry-run. Savepoint atomic; caller owns the outer commit/rollback.

    SQLite takes BEGIN IMMEDIATE when no driver transaction is active; existing
    caller transactions must be retried in full on lock/snapshot failure. PostgreSQL
    serializes this SKU with FOR UPDATE. Callers must use this API for every edge.
    """
    _clean(session)
    plan = ReplacementPlan.model_validate(plan.model_dump(mode="python"))
    at = _now(now)
    if apply:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            driver = connection.connection.driver_connection
            if not driver.in_transaction:  # type: ignore[union-attr]
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            _require(connection.dialect.name == "postgresql", "unsupported_write_dialect")

    def execute() -> ReplacementResult:
        session.expire_all()
        if apply:
            _require(
                session.scalar(
                    select(PriceSKU).where(PriceSKU.id == plan.old.price_sku_id).with_for_update()
                )
                is not None,
                "price_sku_missing",
            )
            session.execute(
                select(PriceSnapshot)
                .where(PriceSnapshot.id.in_((*_ids(plan.old), *_ids(plan.new))))
                .order_by(PriceSnapshot.id)
                .with_for_update()
            ).all()
        _fresh_plan(session, plan, verifier, at)
        receipts = _for_sku(_ledger(session), plan.old.price_sku_id)
        existing = [r for r in receipts if r.plan.plan_sha256 == plan.plan_sha256]
        if existing:
            _require(len(existing) == 1 and existing[0].plan == plan, "idempotency_conflict")
            retired = {r.price_id for receipt in receipts for r in receipt.plan.old.rates}
            _require(not retired.intersection(_ids(plan.new)), "successor_already_retired")
            return ReplacementResult(
                plan_sha256=plan.plan_sha256,
                receipt_sha256=existing[0].receipt_sha256,
                applied=apply,
                created=False,
                replaced_prices=len(plan.old.rates),
            )
        _require(_ledger_hash(receipts) == plan.expected_lifecycle_sha256, "lifecycle_cas_conflict")
        _available(plan.old, plan.new, receipts)
        if not apply:
            return ReplacementResult(
                plan_sha256=plan.plan_sha256,
                receipt_sha256=None,
                applied=False,
                created=False,
                replaced_prices=len(plan.old.rates),
            )
        receipt = ReplacementReceipt(plan=plan, applied_at=at, receipt_sha256="0" * 64)
        receipt = receipt.model_copy(update={"receipt_sha256": _receipt_hash(receipt)})
        _append(session, receipt)
        session.expire_all()
        _require(any(r == receipt for r in _ledger(session)), "persisted_receipt_mismatch")
        _fresh_plan(session, plan, verifier, at)
        return ReplacementResult(
            plan_sha256=plan.plan_sha256,
            receipt_sha256=receipt.receipt_sha256,
            applied=True,
            created=True,
            replaced_prices=len(plan.old.rates),
        )

    if apply:
        with session.begin_nested():
            return execute()
    with session.no_autoflush:
        return execute()


def resolve_price(
    session: Session,
    price_id: int,
    *,
    verifier: ProofVerifier,
    now: datetime | None = None,
) -> PriceDisposition:
    """Read-only live disposition; superseded is NOT permission to use the old row.

    Superseded returns a current leaf only when all linked complete groups validate.
    Consumers must build new cost rows referencing that leaf; never rewrite history.
    Corrupt dedicated audit state blocks resolution rather than hiding an old edge.
    """
    try:
        _clean(session)
        session.expire_all()
        at = _now(now)
        with session.no_autoflush:
            row = _price(session, price_id)
            receipts = _for_sku(_ledger(session), row.price_sku_id)
            edges = {
                a.price_id: (b.price_id, receipt)
                for receipt in receipts
                for a, b in _pairs(receipt.plan)
            }
            # Incoming receipts must validate too: a new row alone is not proof of activation.
            involved = {price_id}
            path = [price_id]
            while path[-1] in edges:
                nxt = edges[path[-1]][0]
                _require(nxt not in path, "lifecycle_cycle")
                path.append(nxt)
                involved.add(nxt)
            selected: list[ReplacementReceipt] = []
            changed = True
            while changed:
                changed = False
                for receipt in receipts:
                    ids = set(_ids(receipt.plan.old)) | set(_ids(receipt.plan.new))
                    if ids & involved and receipt not in selected:
                        selected.append(receipt)
                        involved.update(ids)
                        changed = True
            fresh: dict[tuple[tuple[int, ...], Purpose], VerifiedPriceGroup] = {}
            for receipt in selected:
                _require(
                    receipt.applied_at.tzinfo is not None and _utc(receipt.applied_at) <= at,
                    "receipt_from_future",
                )
                for expected in (receipt.plan.old, receipt.plan.new):
                    purpose: Purpose = (
                        "historical" if set(_ids(expected)) & set(edges) else "current"
                    )
                    key = (_ids(expected), purpose)
                    if key not in fresh:
                        fresh[key] = _verify(session, key[0], verifier, purpose, at)
                    actual_state, expected_state = _proof_state(fresh[key]), _proof_state(expected)
                    if purpose != expected.purpose:
                        # Intermediate prices are now history: validate immutable rate/row
                        # bindings freshly, without resurrecting a retired policy approval.
                        for state in (actual_state, expected_state):
                            for name in (
                                "purpose",
                                "current_policy_verified",
                                "policy_evidence",
                                "dependency_sha256",
                            ):
                                state.pop(name)
                    _require(actual_state == expected_state, "receipt_dependency_changed")
            leaf = path[-1]
            proof = next(
                (p for (ids, purpose), p in fresh.items() if leaf in ids and purpose == "current"),
                None,
            )
            if proof is None:
                proof = _verify(session, (leaf,), verifier, "current", at)
            _require(not set(_ids(proof)) & set(edges), "mixed_current_and_retired_tiers")
            return PriceDisposition(
                price_id=price_id,
                status="superseded" if len(path) > 1 else "current",
                successor_id=path[1] if len(path) > 1 else None,
                current_price_id=leaf,
                replacement_path=tuple(path),
                receipt_sha256s=tuple(sorted(r.receipt_sha256 for r in selected)),
                proof_sha256=_hash(_proof_state(proof)),
                diagnostics=("validated_internal_replacement",) if len(path) > 1 else (),
            )
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ArithmeticError) as exc:
        reason = str(exc) if isinstance(exc, LifecycleConflict) else "lifecycle_resolution_failed"
        return PriceDisposition(price_id=price_id, status="blocked", diagnostics=(reason,))
