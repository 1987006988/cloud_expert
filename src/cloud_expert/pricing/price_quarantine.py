"""Evidence-preserving quarantine of two explicitly supported legacy AWS defects.

This is deterministic rejection, not price validation, supersession, model review
or customer approval. Corruption/missing proof stays blocked, never quarantined.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, or_, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing import price_lifecycle as life
from cloud_expert.pricing.aws_billing_policy import canonical, digest, utc
from cloud_expert.pricing.aws_catalog_promotion import RULE as CATALOG_RULE
from cloud_expert.pricing.aws_catalog_promotion import decimal8
from cloud_expert.pricing.extraction import _record_from_aws_s3_dimension
from cloud_expert.pricing.official_catalog import (
    MAX_BYTES,
    CatalogSelection,
    decode_catalog_json,
    inspect_official_catalog,
)

RULE: Final = "legacy_aws_price_quarantine_v1"
ACTOR = "deterministic_price_quarantine"
PREFIX = "PRICE-QUARANTINE-"
STATE = "blocked_by_deterministic_check"
FIRST_RULE = "aws_s3_standard_storage_first_tier_v1"
type Reason = Literal["incomplete_graduated_catalog_group", "withdrawn_storage_unit_policy"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DefectProof(_Record):
    reason: Reason
    price_ids: tuple[int, ...]
    price_fingerprints: dict[str, str]
    evidence_ids: tuple[int, ...]
    evidence_fingerprints: dict[str, str]
    catalog_rate_codes: tuple[str, ...]
    recorded_rate_codes: tuple[str, ...]
    dependency_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class QuarantinePlan(_Record):
    rule_version: Literal["legacy_aws_price_quarantine_v1"] = RULE
    prepared_at: datetime
    proofs: tuple[DefectProof, ...]
    expected_audit_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class QuarantineReceipt(_Record):
    plan: QuarantinePlan
    applied_at: datetime
    receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def _require(value: object, code: str) -> None:
    if not value:
        raise life.LifecycleConflict(code)


def _clean(session: Session, now: datetime) -> None:
    _require(not (session.new or session.dirty or session.deleted), "clean_session_required")
    _require(now.tzinfo is not None, "aware_time_required")
    session.expire_all()


def _hash(record: BaseModel, exclude: str) -> str:
    return digest(canonical(record.model_dump(mode="json", exclude={exclude})))


def _ids(plan: QuarantinePlan) -> tuple[int, ...]:
    ids = tuple(sorted(i for proof in plan.proofs for i in proof.price_ids))
    _require(ids and len(set(ids)) == len(ids), "empty_or_duplicate_quarantine_targets")
    return ids


def _path(root: Path, relative: str) -> Path:
    parts = PureWindowsPath(relative)
    _require(not parts.drive and not parts.root and ".." not in parts.parts, "unsafe_raw_path")
    result = (root.resolve() / parts.as_posix()).resolve()
    _require(result.is_relative_to(root.resolve()) and result.is_file(), "raw_path_missing")
    return result


def _archived_row(row: SnapshotRecord | SourceDocument) -> dict[str, Any]:
    # Refresh retires these records without changing their retained factual content.
    # This exclusion is local to rejection, never a current-price validity rule.
    return {k: v for k, v in life._row(row).items() if k not in {"is_current", "updated_at"}}


def _evidence_fingerprint(session: Session, evidence_id: int) -> str:
    ev = session.get(Evidence, evidence_id)
    _require(ev is not None and ev.snapshot_record_id is not None, "evidence_missing")
    assert ev is not None and ev.snapshot_record_id is not None
    snapshot = session.get(SnapshotRecord, ev.snapshot_record_id)
    _require(snapshot is not None and ev.source_document is not None, "snapshot_missing")
    assert snapshot is not None
    _require(snapshot.source_document_id == ev.source_document_id, "evidence_snapshot_mismatch")
    return life._hash([life._row(ev), _archived_row(ev.source_document), _archived_row(snapshot)])


def _price_fingerprint(session: Session, price: PriceSnapshot) -> str:
    sku = price.price_sku
    _require(sku is not None and sku.region is not None, "price_scope_missing")
    _require(sku.product is not None and sku.provider is not None, "price_owner_missing")
    partition = sku.region.cloud_partition
    _require(partition is not None, "price_partition_missing")
    return life._hash(
        [
            life._row(price),
            life._row(sku),
            life._row(sku.region),
            life._row(partition),
            life._row(sku.product),
            life._row(sku.provider),
            _evidence_fingerprint(session, price.evidence_id),
        ]
    )


def _archive(session: Session, snapshot_id: int, root: Path, now: datetime) -> tuple[Any, ...]:
    """Verify retained bytes without treating obsolete/disallowed sources as admitted."""
    snapshot = session.get(SnapshotRecord, snapshot_id)
    _require(snapshot is not None, "snapshot_missing")
    assert snapshot is not None
    doc = snapshot.source_document
    entry = get_entry_by_source_id(snapshot.source_id)
    _require(
        entry is not None
        and doc is not None
        and doc.provider.code == "aws"
        and entry.provider_code == "aws"
        and entry.product_code == "s3"
        and entry.market_mode == "international"
        and entry.cloud_partition == "aws"
        and doc.source_type == entry.source_type == "pricing"
        and doc.cloud_partition == "aws"
        and doc.content_hash == snapshot.content_hash
        and doc.storage_path == snapshot.storage_path
        and doc.http_status == 200
        and doc.mime_type == snapshot.content_type
        and utc(doc.captured_at) == utc(snapshot.captured_at) <= utc(now),
        "archive_identity_mismatch",
    )
    assert entry is not None
    raw_path = _path(root, snapshot.storage_path)
    manifest_path = _path(root, snapshot.manifest_path)
    _require(
        raw_path.stat().st_size == snapshot.content_length_bytes <= MAX_BYTES, "raw_size_mismatch"
    )
    raw = raw_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    manifest = decode_catalog_json(manifest_bytes, limit=1024 * 1024)
    _require(
        digest(raw) == snapshot.content_hash
        and manifest.get("schema_version") == "1.0"
        and manifest.get("content_sha256") == snapshot.content_hash
        and manifest.get("content_length_bytes") == len(raw)
        and manifest.get("storage_path") == snapshot.storage_path
        and manifest.get("http_status") == 200
        and manifest.get("content_type") == snapshot.content_type
        and manifest.get("source_id") == snapshot.source_id
        and manifest.get("requested_url") == entry.url
        and manifest.get("final_url") == doc.url
        and utc(datetime.fromisoformat(manifest["captured_at"])) == utc(snapshot.captured_at)
        and all(
            manifest.get(k) == getattr(entry, k)
            for k in ("provider_code", "product_code", "market_mode", "source_type")
        ),
        "archive_raw_or_manifest_mismatch",
    )
    binding = {
        "snapshot_id": snapshot.id,
        "snapshot": _archived_row(snapshot),
        "source": _archived_row(doc),
        "raw_sha256": digest(raw),
        "manifest_sha256": digest(manifest_bytes),
        "registry_sha256": digest(canonical(entry.model_dump(mode="json"))),
    }
    return snapshot, entry, manifest, raw, binding


def _evidence(ev: Evidence) -> None:
    _require(
        ev.content_hash == digest(ev.excerpt) and ev.snapshot_record_id is not None,
        "evidence_hash_or_link_invalid",
    )


def _inventory(session: Session, peers: list[PriceSnapshot], evidence_ids: set[int]) -> str:
    # Peers are the complete original SKU + catalog snapshot + parser group.
    # Other captures, unreferenced evidence and replacement parsers are not this defect.
    evidence = list(
        session.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids)).order_by(Evidence.id))
    )
    _require({ev.id for ev in evidence} == evidence_ids, "inventory_evidence_missing")
    return life._hash(
        {
            "prices": [(p.id, _price_fingerprint(session, p)) for p in peers],
            "evidence": [(ev.id, _evidence_fingerprint(session, ev.id)) for ev in evidence],
        }
    )


def _group_proof(session: Session, price_id: int, root: Path, now: datetime) -> DefectProof:
    price = session.get(PriceSnapshot, price_id)
    _require(price is not None, "price_missing")
    assert price is not None
    sku, ev = price.price_sku, price.evidence
    partition = sku.region.cloud_partition
    _require(
        sku.provider.code == "aws"
        and sku.product.code == "s3"
        and sku.provider_id
        == sku.product.provider_id
        == sku.region.provider_id
        == ev.source_document.provider_id
        and sku.region.code == "us-east-1"
        and sku.region.country_code == "US"
        and sku.product.market_mode == sku.region.market_mode == "international"
        and partition is not None
        and partition.partition_code == "aws"
        and partition.provider_id == sku.provider_id
        and partition.market_mode == "international"
        and sku.charge_category == "storage"
        and sku.billing_mode == "on_demand"
        and sku.currency == "USD"
        and sku.tax_included is False
        and ev.parser_rule in {FIRST_RULE, CATALOG_RULE},
        "unsupported_quarantine_scope",
    )
    _evidence(ev)
    assert ev.snapshot_record_id is not None
    snapshot, entry, manifest, raw, binding = _archive(session, ev.snapshot_record_id, root, now)
    _require(entry.source_id == "aws_s3_pricing_bulk_us_east_1", "unsupported_catalog_source")
    payload = decode_catalog_json(raw)
    if ev.parser_rule == FIRST_RULE:
        match = re.match(r"^json:products\.([A-Za-z0-9]+);", ev.locator)
        _require(match is not None, "unsupported_legacy_locator")
        assert match is not None
        code = match[1]
        product = payload["products"][code]
        selection = CatalogSelection(
            sku=code, product_family="Storage", attributes=product["attributes"], unit="GB-Mo"
        )
    else:
        extracted = decode_catalog_json(ev.excerpt.encode(), limit=8 * 1024 * 1024)
        code = extracted["catalog_record"]["sku"]
        choices = [
            CatalogSelection.model_validate(s)
            for s in extracted["promotion_config"]["selections"]
            if s["sku"] == code
        ]
        _require(len(choices) == 1, "ambiguous_catalog_selection")
        selection = choices[0]
    _require(
        selection.product_family == "Storage"
        and selection.unit == "GB-Mo"
        and selection.attributes.get("volumeType") == "Standard"
        and selection.attributes.get("storageClass") == "General Purpose"
        and selection.attributes.get("usagetype") == "TimedStorage-ByteHrs",
        "unsupported_storage_catalog_scope",
    )
    # Inspect the historical catalog at its actual capture time, not as today's quote.
    inspected = inspect_official_catalog(
        raw,
        entry=entry,
        manifest=manifest,
        selections=[selection],
        as_of=utc(snapshot.captured_at),
        max_age_days=1,
    )
    rates = inspected["records"]
    peers = list(
        session.scalars(
            select(PriceSnapshot)
            .join(Evidence)
            .where(
                PriceSnapshot.price_sku_id == sku.id,
                Evidence.snapshot_record_id == snapshot.id,
                Evidence.parser_rule == ev.parser_rule,
            )
            .order_by(PriceSnapshot.id)
        )
    )
    evidence_ids = {p.evidence_id for p in peers}
    dependencies = [binding]
    recorded = []
    if ev.parser_rule == FIRST_RULE:
        _require(
            len(peers) == 1 and len(rates) > 1 and rates[0]["end_range"] != "Inf",
            "incomplete_group_defect_not_proven",
        )
        rate = rates[0]
        term = rate["rate_code"].rsplit(".", 1)[0]
        dimension = payload["terms"]["OnDemand"][code][term]["priceDimensions"][rate["rate_code"]]
        original = _record_from_aws_s3_dimension(
            sku=code,
            offer_term_code=term,
            rate_code=rate["rate_code"],
            dimension=dimension,
            snapshot=snapshot,
            document=snapshot.source_document,
        )
        _require(
            original is not None
            and ev.locator == original.evidence_locator
            and ev.excerpt == original.evidence_excerpt
            and sku.provider_price_code == original.provider_price_code
            and sku.billing_unit == "GB-month",
            "legacy_first_tier_identity_mismatch",
        )
        reason: Reason = "incomplete_graduated_catalog_group"
        by_locator = {ev.locator: rate}
    else:
        _require(
            sku.provider_price_code == f"aws:us-east-1:{code}" and sku.billing_unit == "GiB-month",
            "unsupported_legacy_storage_identity",
        )
        by_locator = {r["price_locator"]: r for r in rates}
        _require(
            {p.evidence.locator for p in peers} == set(by_locator) and len(peers) == len(rates),
            "partial_storage_policy_group",
        )
        reason = "withdrawn_storage_unit_policy"
    for peer in peers:
        _evidence(peer.evidence)
        rate = by_locator.get(peer.evidence.locator)
        _require(rate is not None, "legacy_rate_missing")
        assert rate is not None
        capture_matches = utc(peer.captured_at) == utc(snapshot.captured_at)
        if ev.parser_rule == FIRST_RULE and not capture_matches:
            # The original importer omitted captured_at: both columns used DB insert time.
            # Bind that distinct time for rejection only, never as source freshness.
            original_path = Path(peer.source_payload_path or "")
            _require(
                utc(peer.captured_at) == utc(peer.created_at)
                and utc(snapshot.captured_at) <= utc(peer.captured_at) <= utc(now)
                and original_path.is_absolute()
                and original_path.resolve() == _path(root, snapshot.storage_path),
                "unsupported_legacy_capture_timestamp",
            )
            dependencies.append(
                {
                    "legacy_timestamp_basis": "database_insert_default_rejection_only",
                    "price_id": peer.id,
                    "price_captured_at": utc(peer.captured_at).isoformat(),
                    "price_created_at": utc(peer.created_at).isoformat(),
                    "snapshot_captured_at": utc(snapshot.captured_at).isoformat(),
                    "original_source_payload_path": peer.source_payload_path,
                }
            )
            capture_matches = True
        _require(
            peer.unit_price == decimal8(rate["unit_price"])
            and peer.minimum_quantity == decimal8(rate["begin_range"])
            and peer.maximum_quantity
            == (None if rate["end_range"] == "Inf" else decimal8(rate["end_range"]))
            and peer.billing_period == "monthly"
            and peer.discount_type == "list"
            and capture_matches,
            "stored_catalog_rate_mismatch",
        )
        recorded.append(rate["rate_code"])
        if ev.parser_rule == FIRST_RULE:
            continue
        data = decode_catalog_json(peer.evidence.excerpt.encode(), limit=8 * 1024 * 1024)
        _require(
            data["rule_version"] == CATALOG_RULE
            and data["catalog_record"] == rate
            and data["raw_sha256"] == snapshot.content_hash
            and data["snapshot_record_id"] == snapshot.id
            and data["source_document_id"] == snapshot.source_document_id,
            "legacy_catalog_payload_mismatch",
        )
        refs = data["policy_evidence_references"]
        _require(
            {r["kind"] for r in refs} == {"tax", "storage_unit", "storage_period"}
            and len(refs) == 3,
            "exact_legacy_policy_dependencies_required",
        )
        for ref in refs:
            policies = list(
                session.scalars(
                    select(Evidence).where(
                        Evidence.snapshot_record_id == ref["snapshot_record_id"],
                        Evidence.locator == ref["locator"],
                        Evidence.parser_rule == ref["parser_rule"],
                    )
                )
            )
            _require(len(policies) == 1, "policy_evidence_missing_or_ambiguous")
            policy = policies[0]
            _evidence(policy)
            assert policy.snapshot_record_id is not None
            policy_payload = decode_catalog_json(policy.excerpt.encode(), limit=1024 * 1024)
            _require(
                policy.content_hash == ref["content_hash"]
                and policy.source_document_id == ref["source_document_id"]
                and policy.parser_rule == "aws_official_billing_policy_v1"
                and policy.evidence_type == "html_section"
                and policy_payload["kind"] == ref["kind"]
                and policy_payload["snapshot_record_id"] == policy.snapshot_record_id
                and policy_payload["raw_sha256"] == ref["raw_sha256"],
                "policy_reference_changed",
            )
            ps, registry, _, _, dep = _archive(session, policy.snapshot_record_id, root, now)
            _require(
                ps.source_id == "aws_s3_pricing"
                and registry.terms_review_status == "disallowed"
                and not registry.enabled
                and not registry.allow_automated_fetch
                and registry.automated_fetch_allowed is False
                and registry.reviewed_at is not None
                and utc(registry.reviewed_at) <= utc(now)
                and ps.content_hash == ref["raw_sha256"],
                "policy_withdrawal_not_proven",
            )
            # Hash retained HTML only: do not extract/reuse its withdrawn pricing claims.
            evidence_ids.add(policy.id)
            if dep not in dependencies:
                dependencies.append(dep)
    return DefectProof(
        reason=reason,
        price_ids=tuple(p.id for p in peers),
        price_fingerprints={str(p.id): _price_fingerprint(session, p) for p in peers},
        evidence_ids=tuple(sorted(evidence_ids)),
        evidence_fingerprints={
            str(i): _evidence_fingerprint(session, i) for i in sorted(evidence_ids)
        },
        catalog_rate_codes=tuple(r["rate_code"] for r in rates),
        recorded_rate_codes=tuple(recorded),
        dependency_sha256=life._hash(dependencies),
        inventory_sha256=_inventory(session, peers, evidence_ids),
    )


def _proofs(
    session: Session, ids: tuple[int, ...], root: Path, now: datetime
) -> tuple[DefectProof, ...]:
    _require(
        ids and len(set(ids)) == len(ids) and all(type(i) is int and i > 0 for i in ids),
        "explicit_unique_price_ids_required",
    )
    result: list[DefectProof] = []
    seen: set[int] = set()
    for price_id in sorted(ids):
        if price_id in seen:
            continue
        proof = _group_proof(session, price_id, root, now)
        _require(set(proof.price_ids).issubset(ids), "complete_defect_group_required")
        seen.update(proof.price_ids)
        result.append(proof)
    return tuple(result)


def _records(receipt: QuarantineReceipt, proof: DefectProof) -> list[dict[str, Any]]:
    return [
        {
            "rule_version": RULE,
            "disposition": "quarantined",
            "consumable": False,
            "reason": proof.reason,
            "group_price_ids": list(proof.price_ids),
            "plan_sha256": receipt.plan.plan_sha256,
            "receipt_sha256": receipt.receipt_sha256,
        }
    ]


def _ledger(session: Session) -> list[QuarantineReceipt]:
    # Header labels are validated, not trusted as the only discovery index.
    # Receipt bodies and linked findings keep damaged runs visible to validation.
    finding_runs = select(ModelReviewFinding.run_id).where(
        ModelReviewFinding.verdict == "quarantined_invalid_price"
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
    receipts: list[QuarantineReceipt] = []
    seen_prices: set[int] = set()
    event_ids: set[int] = set()
    for run in runs:
        receipt = QuarantineReceipt.model_validate(run.summary_json)
        plan = receipt.plan
        ids = _ids(plan)
        _require(not seen_prices.intersection(ids), "duplicate_quarantine_history")
        seen_prices.update(ids)
        _require(
            _hash(plan, "plan_sha256") == plan.plan_sha256
            and _hash(receipt, "receipt_sha256") == receipt.receipt_sha256
            and run.run_code == PREFIX + plan.plan_sha256
            and run.reviewer_model == ACTOR
            and run.policy_version == RULE
            and run.input_fingerprint == plan.plan_sha256
            and utc(run.reviewed_at) == utc(receipt.applied_at)
            and plan.prepared_at.tzinfo is not None
            and receipt.applied_at.tzinfo is not None
            and plan.prepared_at <= receipt.applied_at,
            "quarantine_receipt_mismatch",
        )
        _require(
            plan.expected_audit_sha256 == _audit_hash(receipts), "quarantine_history_cas_mismatch"
        )
        findings = list(
            session.scalars(select(ModelReviewFinding).where(ModelReviewFinding.run_id == run.id))
        )
        _require(
            len(findings) == len(ids) and {f.subject_id for f in findings} == set(ids),
            "quarantine_group_incomplete",
        )
        for finding in findings:
            proof = next(p for p in plan.proofs if finding.subject_id in p.price_ids)
            _require(
                finding.subject_type == "price_snapshot"
                and finding.verdict == "quarantined_invalid_price"
                and finding.reason_code == proof.reason
                and finding.rationale == receipt.receipt_sha256
                and finding.input_hash == plan.plan_sha256
                and finding.evidence_ids == list(proof.evidence_ids),
                "quarantine_finding_mismatch",
            )
            assignments = list(
                session.scalars(
                    select(ModelReviewAssignment).where(
                        ModelReviewAssignment.precheck_finding_id == finding.id
                    )
                )
            )
            _require(len(assignments) == 1, "quarantine_assignment_missing")
            assignment = assignments[0]
            _require(
                assignment.precheck_run_id == run.id
                and assignment.target_type == "price_snapshot"
                and assignment.target_id == finding.subject_id
                and assignment.input_hash == plan.plan_sha256
                and assignment.review_state == STATE
                and assignment.prior_review_status is None
                and assignment.evidence_ids == list(proof.evidence_ids)
                and utc(assignment.created_at) == utc(receipt.applied_at)
                and utc(assignment.updated_at) == utc(receipt.applied_at),
                "quarantine_assignment_mismatch",
            )
            events = list(
                session.scalars(
                    select(ModelReviewAuditEvent).where(
                        ModelReviewAuditEvent.assignment_id == assignment.id
                    )
                )
            )
            _require(len(events) == 1, "quarantine_event_missing_or_extra")
            ev = events[0]
            event_ids.add(ev.id)
            _require(
                ev.event_code == f"{PREFIX}{plan.plan_sha256}:{finding.subject_id}"
                and ev.source == ACTOR
                and ev.model_id is None
                and ev.previous_status is None
                and ev.new_status == STATE
                and ev.reason == proof.reason
                and ev.downstream_rebuild_required
                and utc(ev.timestamp) == utc(receipt.applied_at)
                and ev.affected_records == _records(receipt, proof),
                "quarantine_event_mismatch",
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
    _require(observed == event_ids, "orphan_quarantine_event")
    return receipts


def _audit_hash(receipts: list[QuarantineReceipt]) -> str:
    return life._hash([r.receipt_sha256 for r in receipts])


def prepare_price_quarantine(
    session: Session, price_ids: list[int], *, raw_root: Path, now: datetime | None = None
) -> QuarantinePlan:
    at = now or datetime.now(UTC)
    _clean(session, at)
    with session.no_autoflush:
        proofs = _proofs(session, tuple(price_ids), raw_root, at)
        receipts = _ledger(session)
        _require(
            not set(price_ids).intersection(i for r in receipts for i in _ids(r.plan)),
            "already_quarantined_use_saved_plan",
        )
        plan = QuarantinePlan(
            prepared_at=at,
            proofs=proofs,
            expected_audit_sha256=_audit_hash(receipts),
            plan_sha256="0" * 64,
        )
        return plan.model_copy(update={"plan_sha256": _hash(plan, "plan_sha256")})


def _append(session: Session, receipt: QuarantineReceipt) -> None:
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
    for proof in plan.proofs:
        for price_id in proof.price_ids:
            finding = ModelReviewFinding(
                run_id=run.id,
                subject_type="price_snapshot",
                subject_id=price_id,
                verdict="quarantined_invalid_price",
                reason_code=proof.reason,
                rationale=receipt.receipt_sha256,
                evidence_ids=list(proof.evidence_ids),
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
                review_state=STATE,
                prior_review_status=None,
                evidence_ids=list(proof.evidence_ids),
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
                    new_status=STATE,
                    source=ACTOR,
                    model_id=None,
                    reason=proof.reason,
                    timestamp=at,
                    affected_records=_records(receipt, proof),
                    downstream_rebuild_required=True,
                )
            )
    session.flush()


def apply_price_quarantine(
    session: Session,
    plan: QuarantinePlan,
    *,
    expected_plan_sha256: str,
    raw_root: Path,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomic audit append only; caller owns the outer commit/rollback and retries."""
    at = now or datetime.now(UTC)
    _clean(session, at)
    plan = QuarantinePlan.model_validate(plan.model_dump(mode="python"))
    _require(
        plan.plan_sha256 == expected_plan_sha256 == _hash(plan, "plan_sha256"),
        "quarantine_plan_hash_mismatch",
    )
    _require(
        plan.prepared_at.tzinfo is not None and plan.prepared_at <= at, "future_quarantine_plan"
    )
    ids = _ids(plan)
    if apply:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            if not connection.connection.driver_connection.in_transaction:  # type: ignore[union-attr]
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            _require(connection.dialect.name == "postgresql", "unsupported_write_dialect")

    def execute() -> dict[str, Any]:
        if apply:
            # All supported quarantines belong to this provider: serialize global audit CAS.
            session.execute(select(Provider).where(Provider.code == "aws").with_for_update()).all()
            session.execute(
                select(PriceSnapshot)
                .where(PriceSnapshot.id.in_(ids))
                .order_by(PriceSnapshot.id)
                .with_for_update()
            ).all()
        _clean(session, at)
        _require(
            _proofs(session, ids, raw_root, at) == plan.proofs, "quarantine_dependency_changed"
        )
        receipts = _ledger(session)
        existing = [r for r in receipts if r.plan.plan_sha256 == plan.plan_sha256]
        result = {
            "plan_sha256": plan.plan_sha256,
            "applied": apply,
            "created": False,
            "transaction_committed": False,
            "price_ids": list(ids),
            "consumable": False,
            "customer_eligible": False,
            "price_validated": False,
            "approvals_granted": 0,
        }
        if existing:
            _require(
                len(existing) == 1 and existing[0].plan == plan, "quarantine_idempotency_conflict"
            )
            return {**result, "receipt_sha256": existing[0].receipt_sha256}
        _require(
            _audit_hash(receipts) == plan.expected_audit_sha256, "quarantine_audit_cas_conflict"
        )
        _require(
            not set(ids).intersection(i for r in receipts for i in _ids(r.plan)),
            "existing_quarantine_conflict",
        )
        if not apply:
            return {**result, "receipt_sha256": None}
        receipt = QuarantineReceipt(plan=plan, applied_at=at, receipt_sha256="0" * 64)
        receipt = receipt.model_copy(update={"receipt_sha256": _hash(receipt, "receipt_sha256")})
        _append(session, receipt)
        _clean(session, at)
        _require(receipt in _ledger(session), "quarantine_persisted_receipt_mismatch")
        _require(
            _proofs(session, ids, raw_root, at) == plan.proofs, "quarantine_dependency_changed"
        )
        return {**result, "created": True, "receipt_sha256": receipt.receipt_sha256}

    if apply:
        with session.begin_nested():
            return execute()
    with session.no_autoflush:
        return execute()


def quarantine_disposition(
    session: Session, price: PriceSnapshot, raw_root: Path, now: datetime | None = None
) -> life.PriceDisposition | None:
    """Terminal quarantine requires a live proven defect AND an intact full receipt."""
    identity = inspect(price).identity
    price_id = identity[0] if identity else 0
    try:
        at = now or datetime.now(UTC)
        _clean(session, at)
        _require(price_id > 0, "persisted_price_identity_required")
        with session.no_autoflush:
            receipts = [r for r in _ledger(session) if price_id in _ids(r.plan)]
            if not receipts:
                return None
            _require(len(receipts) == 1, "missing_or_ambiguous_quarantine_receipt")
            receipt = receipts[0]
            _require(receipt.applied_at <= at, "future_quarantine_receipt")
            _require(
                _proofs(session, _ids(receipt.plan), raw_root, at) == receipt.plan.proofs,
                "quarantine_dependency_changed",
            )
            return life.PriceDisposition(
                price_id=price_id,
                status="quarantined",
                receipt_sha256s=(receipt.receipt_sha256,),
                proof_sha256=life._hash([p.model_dump(mode="json") for p in receipt.plan.proofs]),
                diagnostics=(
                    "deterministic_rejection_not_price_validation",
                    "replacement_price_and_cost_coverage_unresolved",
                    *(p.reason for p in receipt.plan.proofs if price_id in p.price_ids),
                ),
            )
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ArithmeticError) as exc:
        reason = str(exc) if isinstance(exc, life.LifecycleConflict) else "quarantine_proof_failed"
        return life.PriceDisposition(price_id=price_id, status="blocked", diagnostics=(reason,))
