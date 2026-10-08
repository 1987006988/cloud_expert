"""Append-only expiry of three receipt-bound AWS remediation groups. Never approval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, or_, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.pricing import aws_document_catalog as docs
from cloud_expert.pricing import aws_document_policy as policy
from cloud_expert.pricing import aws_price_replacement as replacement
from cloud_expert.pricing import price_lifecycle as life
from cloud_expert.pricing.aws_billing_policy import (
    canonical,
    digest,
    snapshot_binding,
    utc,
    verified_snapshot_facts,
)
from cloud_expert.pricing.aws_catalog_promotion import _context, decimal8
from cloud_expert.pricing.large_catalog import inspect_large_ec2_catalog_facts
from cloud_expert.pricing.official_catalog import (
    MAX_BYTES,
    decode_catalog_json,
    inspect_official_catalog_facts,
    validate_official_catalog_source,
)

RULE: Final = "aws_expired_history_v1"
ACTOR = "deterministic_price_expiry"
PREFIX = "PRICE-EXPIRE-"
PAIRS = {13: 19, 17: 20, 18: 21}
VERDICT = "retained_expired_price_history"


class ExpiryConflict(ValueError):
    """Fail closed; not a price-validation result."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SnapshotBaseline(_Record):
    snapshot_id: int = Field(gt=0, strict=True)
    document_id: int = Field(gt=0, strict=True)
    immutable_sha256: life.SHA
    snapshot_updated_at: datetime | None
    document_updated_at: datetime | None


class ExpiredGroup(_Record):
    old_id: int = Field(gt=0, strict=True)
    new_id: int = Field(gt=0, strict=True)
    sku_id: int = Field(gt=0, strict=True)
    replacement_receipt_sha256: life.SHA
    expires_at: datetime
    facts_sha256: life.SHA
    price_sha256s: dict[str, str]
    evidence_sha256s: dict[str, str]
    snapshots: tuple[SnapshotBaseline, ...]


class ExpiryPlan(_Record):
    rule_version: Literal["aws_expired_history_v1"] = RULE
    prepared_at: datetime
    groups: tuple[ExpiredGroup, ...] = Field(min_length=1, max_length=3)
    expected_audit_sha256: life.SHA
    plan_sha256: life.SHA


class ExpiryReceipt(_Record):
    plan: ExpiryPlan
    applied_at: datetime
    receipt_sha256: life.SHA


class ExpiryDisposition(_Record):
    price_id: int
    status: Literal["expired_history", "blocked"]
    successor_id: int | None = None
    current_price_id: None = None
    replacement_path: tuple[int, ...] = ()
    receipt_sha256s: tuple[str, ...] = ()
    proof_sha256: str | None = None
    diagnostics: tuple[str, ...] = ()
    customer_eligible: Literal[False] = False


def _require(value: object, code: str) -> None:
    if not value:
        raise ExpiryConflict(code)


def _clean(session: Session, now: datetime) -> None:
    _require(now.tzinfo is not None and now.utcoffset() is not None, "aware_time_required")
    _require(not (session.new or session.dirty or session.deleted), "clean_session_required")
    session.expire_all()


def _hash(record: BaseModel, exclude: str) -> str:
    return life._hash(record.model_dump(mode="json", exclude={exclude}))


def _ids(plan: ExpiryPlan) -> tuple[int, ...]:
    ids = tuple(sorted(i for g in plan.groups for i in (g.old_id, g.new_id)))
    _require(len(set(ids)) == len(ids), "duplicate_expiry_group")
    _require(all(PAIRS.get(g.old_id) == g.new_id for g in plan.groups), "unsupported_expiry_pair")
    return ids


def _archived_row(row: Any) -> dict[str, Any]:
    return {k: v for k, v in life._row(row).items() if k not in {"is_current", "updated_at"}}


def _snapshot_hash(snapshot: SnapshotRecord) -> str:
    return life._hash([_archived_row(snapshot), _archived_row(snapshot.source_document)])


def _evidence_hash(session: Session, evidence_id: int) -> str:
    evidence = session.get(Evidence, evidence_id)
    _require(evidence is not None and evidence.snapshot_record_id is not None, "evidence_missing")
    assert evidence is not None
    snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
    _require(
        snapshot is not None and snapshot.source_document_id == evidence.source_document_id,
        "evidence_link_mismatch",
    )
    assert snapshot is not None
    return life._hash([life._row(evidence), _snapshot_hash(snapshot)])


def _price_hash(session: Session, price_id: int) -> str:
    price = life._price(session, price_id)
    sku = price.price_sku
    return life._hash(
        [
            life._row(r)
            for r in (price, sku, sku.region, sku.region.cloud_partition, sku.product, sku.provider)
        ]
        + [_evidence_hash(session, price.evidence_id)]
    )


def _replacement(session: Session, old_id: int) -> life.ReplacementReceipt:
    receipts = [r for r in life._ledger(session) if old_id in life._ids(r.plan.old)]
    _require(len(receipts) == 1, "exact_replacement_receipt_required")
    receipt = receipts[0]
    _require(
        old_id in PAIRS
        and life._ids(receipt.plan.old) == (old_id,)
        and life._ids(receipt.plan.new) == (PAIRS[old_id],),
        "unsupported_expiry_pair",
    )
    _require(
        receipt.plan.old.verifier_version == receipt.plan.new.verifier_version == replacement.RULE,
        "unsupported_replacement_verifier",
    )
    return receipt


def _facts(
    session: Session, receipt: life.ReplacementReceipt, root: Path, now: datetime
) -> tuple[str, datetime, tuple[int, ...], tuple[int, ...]]:
    """Re-extract exact retained facts at NOW, never by backdating a current verifier."""
    old_id, new_id = life._ids(receipt.plan.old)[0], life._ids(receipt.plan.new)[0]
    old, new = life._price(session, old_id), life._price(session, new_id)
    _require(
        receipt.applied_at.tzinfo is not None and receipt.applied_at <= now,
        "future_replacement_receipt",
    )
    payload = decode_catalog_json(new.evidence.excerpt.encode(), limit=8 * 1024 * 1024)
    config = docs._Config.model_validate(payload["derivation_config"])
    _require(
        config.model_dump(mode="json") == payload["derivation_config"]
        and len(config.selections) == 1,
        "noncanonical_derivation_config",
    )
    snapshot, entry, manifest, path = verified_snapshot_facts(
        session, config.snapshot_id, raw_root=root, checked_at=now
    )
    binding = snapshot_binding(snapshot, entry, manifest)
    authorization = validate_official_catalog_source(entry)
    product = replacement.SUPPORTED[old_id][1]
    context = _context(session, product)
    _require(
        entry.source_id == f"aws_{product}_pricing_bulk_us_east_1"
        and entry.product_code == product
        and entry.fixture_response_path is None
        and entry.reviewed_at is not None
        and entry.reviewed_at.tzinfo is not None
        and utc(entry.reviewed_at) <= utc(snapshot.captured_at)
        and snapshot.content_length_bytes <= entry.fetch_policy.max_content_length_bytes
        and snapshot.source_document.provider.is_active
        and snapshot.source_document.provider_id == context["provider_id"],
        "catalog_admission_or_context_changed",
    )
    selection = config.selections[0]
    category, unit, period, kinds = docs._selection(selection, product)
    if product == "ec2":
        inspected = inspect_large_ec2_catalog_facts(
            path, entry=entry, manifest=manifest, selections=[selection], checked_at=now
        )
    else:
        _require(snapshot.content_length_bytes <= MAX_BYTES, "catalog_too_large")
        inspected = inspect_official_catalog_facts(
            path.read_bytes(),
            entry=entry,
            manifest=manifest,
            selections=[selection],
            checked_at=now,
        )
    _require(len(inspected["records"]) == 1, "incomplete_or_expanded_catalog_group")
    rate = inspected["records"][0]
    _require(
        {r.kind for r in config.policy_references} == kinds
        and len(config.policy_references) == len(kinds)
        and len({r.evidence_id for r in config.policy_references}) == len(kinds),
        "exact_policy_set_required",
    )
    references = []
    snapshot_ids = {snapshot.id}
    evidence_ids = {old.evidence_id, new.evidence_id}
    for ref in sorted(config.policy_references, key=lambda r: r.kind):
        ev = session.get(Evidence, ref.evidence_id)
        _require(
            ev is not None
            and ev.content_hash == ref.content_hash
            and ev.snapshot_record_id is not None,
            "policy_evidence_changed",
        )
        assert ev is not None and ev.snapshot_record_id is not None
        extracted = policy.prepare_document_policy_facts(
            session, ev.snapshot_record_id, raw_root=root, checked_at=now
        )
        records = [r for r in extracted["records"] if r["kind"] == ref.kind]
        _require(
            len(records) == 1 and docs._evidence_matches(ev, records[0]), "policy_dom_mismatch"
        )
        row = records[0]
        source_id, scope = docs.CLAIMS[ref.kind]
        _require((row["source_id"], row["scope"]) == (source_id, scope), "policy_scope_mismatch")
        peers = list(
            session.scalars(
                select(Evidence.id).where(
                    Evidence.snapshot_record_id == ev.snapshot_record_id,
                    Evidence.locator == ev.locator,
                    Evidence.parser_rule == ev.parser_rule,
                )
            )
        )
        _require(peers == [ev.id], "ambiguous_policy_evidence")
        references.append(
            {
                **ref.model_dump(),
                "reference_type": "aws_document_policy_evidence",
                "scope": scope,
                "source_id": source_id,
                **{
                    k: row[k]
                    for k in (
                        "source_document_id",
                        "snapshot_record_id",
                        "raw_sha256",
                        "source_url",
                        "manifest_sha256",
                        "registry_sha256",
                        "locator",
                        "parser_rule",
                    )
                },
            }
        )
        snapshot_ids.add(ev.snapshot_record_id)
        evidence_ids.add(ev.id)
    sku = {
        **{k: context[k] for k in ("provider_id", "product_id", "region_id")},
        "sku_id": None,
        "provider_price_code": f"aws:us-east-1:{rate['sku']}",
        "charge_category": category,
        "billing_mode": "on_demand",
        "billing_unit": unit,
        "currency": "USD",
        "tax_included": False,
    }
    price = {
        "unit_price": str(decimal8(rate["unit_price"])),
        "minimum_quantity": str(decimal8(rate["begin_range"])),
        "maximum_quantity": None
        if rate["end_range"] == "Inf"
        else str(decimal8(rate["end_range"])),
        "billing_period": period,
        "discount_type": "list",
        "captured_at": binding["captured_at"],
        "effective_from": utc(datetime.fromisoformat(rate["effective_from"])).isoformat(),
        "effective_to": None,
        "source_payload_path": binding["storage_path"],
    }
    group = {
        "catalog_sku": selection.sku,
        "rate_codes": [rate["rate_code"]],
        "complete_ondemand_records_sha256": digest(canonical([rate])),
        "requires_all_tiers": True,
    }
    group["group_sha256"] = digest(canonical({**group, "catalog": binding}))
    expected_payload = {
        **payload,
        **binding,
        **context,
        "catalog_record": rate,
        "catalog_version": inspected["catalog_version"],
        "publication_date": inspected["publication_date"],
        "catalog_disclaimer": inspected["disclaimer"],
        "source_authorization": authorization,
        "policy_evidence_references": references,
        "unit_derivation": docs._unit_proof(rate, selection),
        "field_proofs": docs._field_proofs(rate, kinds),
        "expected_sku_fields": sku,
        "expected_price_fields": price,
        "tier_group": group,
        "rule_version": docs.RULE,
        "scope": "internal_reference_only",
        "tax_status": "general_conditional_exclusive",
        "tax_condition": "except_as_otherwise_noted",
        "tax_included": False,
        "tax_rate": None,
        "customer_payable_tax": "unknown",
        "sku_tax_exception_status": "not_determined",
        "customer_eligible": False,
        "price_approval": False,
        "complete_tco": False,
        "lifecycle_activation_granted": False,
        "hours_per_month": None,
        "price_basis": "public_catalog",
        "realtime": False,
    }
    _require(canonical(expected_payload) == new.evidence.excerpt, "derived_payload_fact_mismatch")
    row = {
        "catalog_sku": selection.sku,
        "rate_code": rate["rate_code"],
        "sku": sku,
        "price": price,
        "evidence": {
            **binding,
            "locator": rate["price_locator"],
            "parser_rule": docs.RULE,
            "evidence_type": "json_path",
            "excerpt": canonical(expected_payload),
            "content_hash": digest(canonical(expected_payload)),
        },
    }
    plan = {
        "rule_version": docs.RULE,
        "config": config.model_dump(mode="json"),
        "catalog": binding,
        "context": context,
        "policy_evidence_references": references,
        "tier_groups": [group],
        "rows": [row],
        "scope": "internal_reference_only",
        "review_required": True,
        "customer_eligible": False,
        "price_approval": False,
        "complete_tco": False,
        "lifecycle_activation_granted": False,
        "database_write_performed": False,
    }
    plan["plan_sha256"] = digest(canonical(plan))
    replacement._shape(old_id, plan)
    replacement._legacy(session, old_id, plan, rate, binding, selection)
    _require(docs._evidence_matches(new.evidence, row["evidence"]), "successor_evidence_changed")
    replacement._same_fields(new, row)
    _require(
        digest(
            canonical(
                {
                    "rule": replacement.RULE,
                    "old_price_id": old_id,
                    "document_plan_sha256": plan["plan_sha256"],
                }
            )
        )
        == receipt.plan.new.dependency_sha256,
        "original_document_plan_changed",
    )
    _require(
        digest(
            canonical(
                {
                    "rule": replacement.RULE,
                    "old_price_id": old_id,
                    "catalog": binding,
                    "context": context,
                }
            )
        )
        == receipt.plan.old.dependency_sha256,
        "original_catalog_plan_changed",
    )
    price_peers = set(
        session.scalars(
            select(PriceSnapshot.id)
            .join(Evidence)
            .where(
                PriceSnapshot.price_sku_id == old.price_sku_id,
                Evidence.snapshot_record_id == snapshot.id,
            )
        )
    )
    _require(price_peers == {old_id, new_id}, "original_price_group_changed")
    captures = []
    for sid in snapshot_ids:
        snap = session.get(SnapshotRecord, sid)
        assert snap is not None
        captures.append(utc(snap.captured_at))
    expires_at = min(captures) + timedelta(days=config.max_age_days)
    original_times = [receipt.plan.old.checked_at, receipt.plan.new.checked_at, receipt.applied_at]
    _require(
        all(t.tzinfo is not None and max(captures) <= t <= expires_at for t in original_times)
        and max(original_times[:2]) <= receipt.applied_at,
        "original_proof_outside_capture_validity_window",
    )
    _require(now > expires_at, "original_window_not_expired")
    return (
        life._hash({"plan": plan, "expiry": expires_at, "receipt": receipt.receipt_sha256}),
        expires_at,
        tuple(sorted(snapshot_ids)),
        tuple(sorted(evidence_ids)),
    )


def _prepare_group(session: Session, old_id: int, root: Path, now: datetime) -> ExpiredGroup:
    receipt = _replacement(session, old_id)
    for proof in (receipt.plan.old, receipt.plan.new):
        _require(
            proof.checked_at.tzinfo is not None and proof.checked_at <= receipt.applied_at,
            "future_original_proof",
        )
        for rate in proof.rates:
            _require(
                life.price_fingerprint(session, rate.price_id) == rate.row_sha256,
                "original_price_fingerprint_changed",
            )
        for ref in proof.policy_evidence:
            _require(
                life.evidence_fingerprint(session, ref.evidence_id) == ref.state_sha256,
                "original_policy_fingerprint_changed",
            )
    facts, expiry, snapshot_ids, evidence_ids = _facts(session, receipt, root, now)
    baselines = []
    for sid in snapshot_ids:
        snapshot = session.get(SnapshotRecord, sid)
        assert snapshot is not None
        _require(
            snapshot.is_current is True and snapshot.source_document.is_current is True,
            "baseline_requires_unarchived_originals",
        )
        baselines.append(
            SnapshotBaseline(
                snapshot_id=sid,
                document_id=snapshot.source_document_id,
                immutable_sha256=_snapshot_hash(snapshot),
                snapshot_updated_at=getattr(snapshot, "updated_at", None),
                document_updated_at=getattr(snapshot.source_document, "updated_at", None),
            )
        )
    return ExpiredGroup(
        old_id=old_id,
        new_id=PAIRS[old_id],
        sku_id=receipt.plan.old.price_sku_id,
        replacement_receipt_sha256=receipt.receipt_sha256,
        expires_at=expiry,
        facts_sha256=facts,
        price_sha256s={str(i): _price_hash(session, i) for i in (old_id, PAIRS[old_id])},
        evidence_sha256s={str(i): _evidence_hash(session, i) for i in evidence_ids},
        snapshots=tuple(baselines),
    )


def _archive_transition(
    session: Session, baseline: SnapshotBaseline, root: Path, recorded: datetime, now: datetime
) -> None:
    snapshot = session.get(SnapshotRecord, baseline.snapshot_id)
    _require(
        snapshot is not None
        and snapshot.source_document_id == baseline.document_id
        and _snapshot_hash(snapshot) == baseline.immutable_sha256,
        "snapshot_immutable_facts_changed",
    )
    assert snapshot is not None
    doc = snapshot.source_document
    changed = not snapshot.is_current or not doc.is_current
    for row, prior in (
        (snapshot, baseline.snapshot_updated_at),
        (doc, baseline.document_updated_at),
    ):
        current = getattr(row, "updated_at", None)
        if life._json(current) != life._json(prior):
            _require(
                changed
                and current is not None
                and recorded <= utc(current) <= now
                and (prior is None or utc(current) >= utc(prior)),
                "unexplained_archive_timestamp",
            )
    current = list(
        session.scalars(
            select(SnapshotRecord).where(
                SnapshotRecord.source_id == snapshot.source_id, SnapshotRecord.is_current.is_(True)
            )
        )
    )
    _require(len(current) == 1, "archive_successor_missing_or_ambiguous")
    if not changed:
        _require(current[0].id == snapshot.id, "original_current_state_inconsistent")
        descendants = session.scalar(
            select(SnapshotRecord.id)
            .where(SnapshotRecord.previous_snapshot_id == snapshot.id)
            .limit(1)
        )
        _require(descendants is None, "original_snapshot_reactivated")
        return
    _require(snapshot.is_current is False, "document_archived_without_snapshot")
    at, seen = current[0], set()
    _require(at.source_document.is_current is True, "archive_successor_document_not_current")
    while at.id != snapshot.id:
        _require(
            at.id not in seen
            and at.source_id == snapshot.source_id
            and utc(at.captured_at) <= now
            and utc(at.captured_at) >= recorded,
            "invalid_archive_chain",
        )
        seen.add(at.id)
        raw = docs._contained(root, at.storage_path)
        manifest_path = docs._contained(root, at.manifest_path)
        manifest = decode_catalog_json(manifest_path.read_bytes(), limit=1024 * 1024)
        with raw.open("rb") as stream:
            from hashlib import file_digest

            actual_hash = file_digest(stream, "sha256").hexdigest()
        _require(
            actual_hash
            == at.content_hash
            == at.source_document.content_hash
            == manifest.get("content_sha256")
            and raw.stat().st_size
            == at.content_length_bytes
            == manifest.get("content_length_bytes")
            and manifest.get("source_id") == snapshot.source_id
            and manifest.get("storage_path") == at.storage_path
            and manifest.get("http_status") == 200
            and manifest.get("requested_url")
            == snapshot.source_document.url
            == manifest.get("final_url")
            and utc(datetime.fromisoformat(manifest["captured_at"])) == utc(at.captured_at),
            "archive_successor_integrity_failed",
        )
        parent = (
            session.get(SnapshotRecord, at.previous_snapshot_id)
            if at.previous_snapshot_id
            else None
        )
        _require(
            parent is not None and utc(parent.captured_at) < utc(at.captured_at),
            "archive_chain_not_later",
        )
        assert parent is not None
        at = parent
    still_used = (
        session.scalar(
            select(SnapshotRecord.id)
            .where(SnapshotRecord.source_document_id == doc.id, SnapshotRecord.is_current.is_(True))
            .limit(1)
        )
        is not None
    )
    _require(doc.is_current is still_used, "document_archive_state_inconsistent")


def _verify_retained(session: Session, receipt: ExpiryReceipt, root: Path, now: datetime) -> None:
    _require(receipt.applied_at <= now, "expiry_receipt_from_future")
    for group in receipt.plan.groups:
        original = _replacement(session, group.old_id)
        _require(
            original.receipt_sha256 == group.replacement_receipt_sha256,
            "replacement_receipt_changed",
        )
        facts, expiry, sids, eids = _facts(session, original, root, now)
        _require(
            facts == group.facts_sha256
            and expiry == group.expires_at
            and tuple(b.snapshot_id for b in group.snapshots) == sids,
            "retained_fact_proof_changed",
        )
        _require(
            group.price_sha256s
            == {str(i): _price_hash(session, i) for i in (group.old_id, group.new_id)}
            and group.evidence_sha256s == {str(i): _evidence_hash(session, i) for i in eids},
            "retained_rows_changed",
        )
        for baseline in group.snapshots:
            _archive_transition(session, baseline, root, receipt.applied_at, now)


def _audit_hash(receipts: list[ExpiryReceipt]) -> str:
    return life._hash([r.receipt_sha256 for r in receipts])


def _records(receipt: ExpiryReceipt, price_id: int) -> list[dict[str, Any]]:
    group = next(g for g in receipt.plan.groups if price_id in (g.old_id, g.new_id))
    return [
        {
            "rule_version": RULE,
            "price_id": price_id,
            "old_id": group.old_id,
            "new_id": group.new_id,
            "receipt_sha256": receipt.receipt_sha256,
            "replacement_receipt_sha256": group.replacement_receipt_sha256,
            "consumable": False,
            "price_approval": False,
        }
    ]


def _ledger(session: Session) -> list[ExpiryReceipt]:
    finding_runs = select(ModelReviewFinding.run_id).where(
        or_(ModelReviewFinding.verdict == VERDICT, ModelReviewFinding.reason_code == RULE)
    )
    runs = session.scalars(
        select(ModelReviewRun)
        .where(
            or_(
                ModelReviewRun.run_code.startswith(PREFIX),
                ModelReviewRun.reviewer_model == ACTOR,
                ModelReviewRun.policy_version == RULE,
                ModelReviewRun.summary_json["plan"]["rule_version"].as_string() == RULE,
                ModelReviewRun.id.in_(finding_runs),
            )
        )
        .order_by(ModelReviewRun.id)
    )
    receipts: list[ExpiryReceipt] = []
    seen: set[int] = set()
    event_ids: set[int] = set()
    for run in runs:
        receipt = ExpiryReceipt.model_validate(run.summary_json)
        plan, ids = receipt.plan, _ids(receipt.plan)
        _require(not seen.intersection(ids), "overlapping_expiry_receipts")
        seen.update(ids)
        _require(
            _hash(plan, "plan_sha256") == plan.plan_sha256
            and _hash(receipt, "receipt_sha256") == receipt.receipt_sha256
            and plan.expected_audit_sha256 == _audit_hash(receipts)
            and run.run_code == PREFIX + plan.plan_sha256
            and run.reviewer_model == ACTOR
            and run.policy_version == RULE
            and run.input_fingerprint == plan.plan_sha256
            and utc(run.reviewed_at) == receipt.applied_at
            and plan.prepared_at.tzinfo is not None
            and receipt.applied_at.tzinfo is not None
            and plan.prepared_at <= receipt.applied_at
            and all(
                g.expires_at.tzinfo is not None and g.expires_at < plan.prepared_at
                for g in plan.groups
            ),
            "expiry_receipt_envelope_mismatch",
        )
        findings = list(
            session.scalars(select(ModelReviewFinding).where(ModelReviewFinding.run_id == run.id))
        )
        _require(
            len(findings) == len(ids) and {f.subject_id for f in findings} == set(ids),
            "expiry_group_incomplete",
        )
        for finding in findings:
            group = next(g for g in plan.groups if finding.subject_id in (g.old_id, g.new_id))
            evidence_ids = sorted(int(i) for i in group.evidence_sha256s)
            _require(
                finding.subject_type == "price_snapshot"
                and finding.verdict == VERDICT
                and finding.reason_code == RULE
                and finding.input_hash == plan.plan_sha256
                and finding.rationale == receipt.receipt_sha256
                and finding.evidence_ids == evidence_ids,
                "expiry_finding_mismatch",
            )
            assignments = list(
                session.scalars(
                    select(ModelReviewAssignment).where(
                        ModelReviewAssignment.precheck_finding_id == finding.id
                    )
                )
            )
            _require(len(assignments) == 1, "expiry_assignment_missing")
            assignment = assignments[0]
            _require(
                assignment.precheck_run_id == run.id
                and assignment.target_type == "price_snapshot"
                and assignment.target_id == finding.subject_id
                and assignment.review_state == "expired"
                and assignment.prior_review_status is None
                and assignment.input_hash == plan.plan_sha256
                and assignment.evidence_ids == evidence_ids
                and utc(assignment.created_at) == receipt.applied_at
                and utc(assignment.updated_at) == receipt.applied_at,
                "expiry_assignment_mismatch",
            )
            events = list(
                session.scalars(
                    select(ModelReviewAuditEvent).where(
                        ModelReviewAuditEvent.assignment_id == assignment.id
                    )
                )
            )
            _require(len(events) == 1, "expiry_event_missing_or_extra")
            ev = events[0]
            event_ids.add(ev.id)
            _require(
                ev.event_code == f"{PREFIX}{plan.plan_sha256}:{finding.subject_id}"
                and ev.source == ACTOR
                and ev.model_id is None
                and ev.previous_status is None
                and ev.new_status == "expired"
                and ev.reason == RULE
                and ev.downstream_rebuild_required
                and utc(ev.timestamp) == receipt.applied_at
                and ev.affected_records == _records(receipt, finding.subject_id),
                "expiry_event_mismatch",
            )
        receipts.append(receipt)
    observed = set(
        session.scalars(
            select(ModelReviewAuditEvent.id).where(
                or_(
                    ModelReviewAuditEvent.source == ACTOR,
                    ModelReviewAuditEvent.event_code.startswith(PREFIX),
                    ModelReviewAuditEvent.affected_records[0]["rule_version"].as_string() == RULE,
                )
            )
        )
    )
    _require(event_ids == observed, "orphan_expiry_event")
    return receipts


def prepare_expired_history(
    session: Session, price_ids: list[int], *, raw_root: Path, now: datetime | None = None
) -> ExpiryPlan:
    """Read-only. Explicit complete old/new pairs; no automatic price selection."""
    at = now or datetime.now(UTC)
    _clean(session, at)
    _require(
        price_ids
        and all(type(i) is int for i in price_ids)
        and len(set(price_ids)) == len(price_ids),
        "unique_explicit_price_ids_required",
    )
    ids = set(price_ids)
    olds = [i for i in sorted(PAIRS) if {i, PAIRS[i]}.issubset(ids)]
    _require(ids == {i for old in olds for i in (old, PAIRS[old])}, "whole_supported_pair_required")
    ledger = _ledger(session)
    _require(
        not any(ids.intersection(_ids(r.plan)) for r in ledger),
        "already_recorded_use_original_plan",
    )
    groups = tuple(_prepare_group(session, i, raw_root, at) for i in olds)
    plan = ExpiryPlan(
        prepared_at=at,
        groups=groups,
        expected_audit_sha256=_audit_hash(ledger),
        plan_sha256="0" * 64,
    )
    return plan.model_copy(update={"plan_sha256": _hash(plan, "plan_sha256")})


def _append(session: Session, receipt: ExpiryReceipt) -> None:
    plan, at = receipt.plan, receipt.applied_at
    run = ModelReviewRun(
        run_code=PREFIX + plan.plan_sha256,
        policy_version=RULE,
        reviewer_model=ACTOR,
        input_fingerprint=plan.plan_sha256,
        reviewed_at=at,
        summary_json=receipt.model_dump(mode="json"),
    )
    session.add(run)
    session.flush()
    for price_id in _ids(plan):
        group = next(g for g in plan.groups if price_id in (g.old_id, g.new_id))
        evidence_ids = sorted(int(i) for i in group.evidence_sha256s)
        finding = ModelReviewFinding(
            run_id=run.id,
            subject_type="price_snapshot",
            subject_id=price_id,
            verdict=VERDICT,
            reason_code=RULE,
            rationale=receipt.receipt_sha256,
            evidence_ids=evidence_ids,
            input_hash=plan.plan_sha256,
        )
        session.add(finding)
        session.flush()
        assignment = ModelReviewAssignment(
            precheck_run_id=run.id,
            precheck_finding_id=finding.id,
            target_type="price_snapshot",
            target_id=price_id,
            input_hash=plan.plan_sha256,
            prior_review_status=None,
            review_state="expired",
            evidence_ids=evidence_ids,
            created_at=at,
            updated_at=at,
        )
        session.add(assignment)
        session.flush()
        session.add(
            ModelReviewAuditEvent(
                assignment_id=assignment.id,
                event_code=f"{PREFIX}{plan.plan_sha256}:{price_id}",
                previous_status=None,
                new_status="expired",
                source=ACTOR,
                model_id=None,
                reason=RULE,
                affected_records=_records(receipt, price_id),
                downstream_rebuild_required=True,
                timestamp=at,
            )
        )
    session.flush()


def apply_expired_history(
    session: Session,
    plan: ExpiryPlan,
    *,
    expected_hash: str,
    raw_root: Path,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One savepoint within caller transaction; hash-pinned replay, never an approval."""
    at = now or datetime.now(UTC)
    _clean(session, at)
    plan = ExpiryPlan.model_validate(plan.model_dump(mode="python"))
    _require(
        plan.plan_sha256 == expected_hash == _hash(plan, "plan_sha256"), "expiry_plan_hash_mismatch"
    )
    _require(
        plan.prepared_at.tzinfo is not None and plan.prepared_at <= at, "expiry_plan_from_future"
    )
    ids = _ids(plan)
    if apply:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            driver = connection.connection.driver_connection
            if not driver.in_transaction:  # type: ignore[union-attr]
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            _require(connection.dialect.name == "postgresql", "unsupported_write_dialect")
            # One global audit CAS order, shared by all supported groups.
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(718342619)")

    def execute() -> dict[str, Any]:
        _clean(session, at)
        if apply:
            session.execute(
                select(PriceSKU)
                .where(PriceSKU.id.in_([g.sku_id for g in plan.groups]))
                .order_by(PriceSKU.id)
                .with_for_update()
            ).all()
        ledger = _ledger(session)
        existing = [r for r in ledger if set(ids).intersection(_ids(r.plan))]
        result: dict[str, Any] = {
            "rule_version": RULE,
            "plan_sha256": plan.plan_sha256,
            "price_ids": list(ids),
            "applied": apply,
            "created": False,
            "transaction_committed": False,
            "approvals_granted": 0,
            "current_prices_granted": 0,
            "customer_eligible": False,
        }
        if existing:
            _require(len(existing) == 1 and existing[0].plan == plan, "expiry_idempotency_conflict")
            _verify_retained(session, existing[0], raw_root, at)
            return {
                **result,
                "receipt_sha256": existing[0].receipt_sha256,
                "status": "already_recorded",
            }
        _require(plan.expected_audit_sha256 == _audit_hash(ledger), "expiry_audit_cas_conflict")
        actual = tuple(_prepare_group(session, g.old_id, raw_root, at) for g in plan.groups)
        _require(actual == plan.groups, "expiry_facts_cas_conflict")
        if not apply:
            return {**result, "status": "planned_expired_history", "prices_planned": len(ids)}
        receipt = ExpiryReceipt(plan=plan, applied_at=at, receipt_sha256="0" * 64)
        receipt = receipt.model_copy(update={"receipt_sha256": _hash(receipt, "receipt_sha256")})
        _append(session, receipt)
        return {
            **result,
            "created": True,
            "status": "expired_history_pending_caller_commit",
            "receipt_sha256": receipt.receipt_sha256,
        }

    if apply:
        with session.begin_nested():
            return execute()
    with session.no_autoflush:
        return execute()


def expired_history_disposition(
    session: Session, price: PriceSnapshot, *, raw_root: Path, now: datetime | None = None
) -> ExpiryDisposition | None:
    """None means no expiry record. Existing invalid records never fall through."""
    identity = inspect(price).identity
    price_id = int(identity[0]) if identity else 0
    try:
        at = now or datetime.now(UTC)
        _clean(session, at)
        _require(price_id > 0, "persisted_price_required")
        receipts = [r for r in _ledger(session) if price_id in _ids(r.plan)]
        if not receipts:
            return None
        _require(len(receipts) == 1, "ambiguous_expiry_history")
        receipt = receipts[0]
        _verify_retained(session, receipt, raw_root, at)
        group = next(g for g in receipt.plan.groups if price_id in (g.old_id, g.new_id))
        return ExpiryDisposition(
            price_id=price_id,
            status="expired_history",
            successor_id=group.new_id if price_id == group.old_id else None,
            replacement_path=(group.old_id, group.new_id)
            if price_id == group.old_id
            else (group.new_id,),
            receipt_sha256s=(receipt.receipt_sha256, group.replacement_receipt_sha256),
            proof_sha256=group.facts_sha256,
            diagnostics=(
                "verified_expired_history_not_consumable",
                "no_current_successor_or_coverage_claim",
            ),
        )
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ArithmeticError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, (ExpiryConflict, life.LifecycleConflict))
            else "expired_history_verification_failed"
        )
        return ExpiryDisposition(price_id=price_id, status="blocked", diagnostics=(reason,))
