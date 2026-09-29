"""Bounded v1-to-document AWS price replacement, never approval or price discovery.

Only the coordinator may apply. Existing rows 13/17/18 are explicit remediation
targets, not a rule for finding similar prices. Old website policies are neither
read nor reauthorized. Catalog/document adapters and lifecycle v1 remain unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.source import Evidence
from cloud_expert.pricing import aws_document_catalog as documents
from cloud_expert.pricing import price_lifecycle as lifecycle
from cloud_expert.pricing.aws_billing_policy import (
    canonical,
    digest,
    evidence_row,
    snapshot_binding,
    verified_snapshot,
)
from cloud_expert.pricing.aws_catalog_promotion import RULE as LEGACY_RULE
from cloud_expert.pricing.aws_catalog_promotion import _context, _price_values, _same
from cloud_expert.pricing.large_catalog import inspect_large_ec2_catalog
from cloud_expert.pricing.official_catalog import (
    MAX_BYTES,
    CatalogSelection,
    decode_catalog_json,
    inspect_official_catalog,
    validate_official_catalog_source,
)

RULE: Final = "aws_price_policy_replacement_v1"
# Explicit remediation identities, not assertions of price or eligibility.
SUPPORTED = {
    13: ("E9YHNFENF4XQBZR6", "s3", "Requests-Tier1"),
    17: ("ZWQ6Q48CRJXX4FXE", "s3", "Requests-Tier2"),
    18: ("2UVH39HPDNC399X4", "ec2", "BoxUsage:m6i.xlarge"),
}


class AWSReplacementPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_version: Literal["aws_price_policy_replacement_v1"] = RULE
    old_price_id: int = Field(strict=True, gt=0)
    old_row_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_plan: dict[str, Any]
    expected_lifecycle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def _require(condition: object, code: str) -> None:
    if not condition:
        raise lifecycle.LifecycleConflict(code)


def _clean(session: Session, now: datetime) -> None:
    _require(now.tzinfo is not None and now.utcoffset() is not None, "aware_time_required")
    _require(not (session.new or session.dirty or session.deleted), "clean_session_required")
    session.expire_all()


def _hash(plan: AWSReplacementPlan) -> str:
    return digest(canonical(plan.model_dump(mode="json", exclude={"plan_sha256"})))


def _shape(old_id: int, plan: dict[str, Any]) -> tuple[CatalogSelection, dict[str, Any]]:
    _require(type(old_id) is int and old_id in SUPPORTED, "unsupported_legacy_price")
    _require(
        plan.get("rule_version") == documents.RULE
        and plan.get("plan_sha256")
        == digest(canonical({k: v for k, v in plan.items() if k != "plan_sha256"})),
        "document_plan_hash_mismatch",
    )
    config = plan["config"]
    _require(len(config["selections"]) == 1, "one_catalog_sku_required")
    selection = CatalogSelection.model_validate(config["selections"][0])
    sku, product, usage = SUPPORTED[old_id]
    _require(
        selection.sku == sku
        and selection.attributes.get("usagetype") == usage
        and plan["context"]["product_code"] == product,
        "unsupported_replacement_scope",
    )
    # Each admitted historical target contains a single complete OnDemand rate.
    # An expanded catalog group is a gap, not permission to retain its first tier.
    _require(
        len(plan["rows"]) == 1
        and len(plan["tier_groups"]) == 1
        and plan["tier_groups"][0]["rate_codes"] == [plan["rows"][0]["rate_code"]]
        and plan["tier_groups"][0]["requires_all_tiers"] is True,
        "incomplete_legacy_tier_group",
    )
    row = plan["rows"][0]
    _require(row["catalog_sku"] == sku, "catalog_sku_mismatch")
    return selection, row


def _catalog_facts(
    session: Session,
    plan: dict[str, Any],
    selection: CatalogSelection,
    *,
    raw_root: Path,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fresh original catalog proof only. Never loads retired website policies."""
    config = plan["config"]
    snapshot, entry, manifest, path = verified_snapshot(
        session,
        config["snapshot_id"],
        raw_root=raw_root,
        as_of=now,
        max_age_days=config["max_age_days"],
    )
    validate_official_catalog_source(entry)
    product = plan["context"]["product_code"]
    _require(
        entry.source_id == f"aws_{product}_pricing_bulk_us_east_1"
        and entry.product_code == product
        and snapshot.source_id == entry.source_id,
        "catalog_source_mismatch",
    )
    if product == "ec2":
        inspected = inspect_large_ec2_catalog(
            path,
            entry=entry,
            manifest=manifest,
            selections=[selection],
            as_of=now,
            max_age_days=config["max_age_days"],
        )
    else:
        _require(snapshot.content_length_bytes <= MAX_BYTES, "catalog_too_large")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        inspected = inspect_official_catalog(
            raw,
            entry=entry,
            manifest=manifest,
            selections=[selection],
            as_of=now,
            max_age_days=config["max_age_days"],
        )
    binding = snapshot_binding(snapshot, entry, manifest)
    _require(binding == plan["catalog"], "catalog_dependency_changed")
    _require(_context(session, product) == plan["context"], "catalog_context_changed")
    payload = decode_catalog_json(plan["rows"][0]["evidence"]["excerpt"].encode())
    _require(
        inspected["records"] == [payload["catalog_record"]]
        and payload["catalog_version"] == inspected["catalog_version"]
        and payload["publication_date"] == inspected["publication_date"],
        "catalog_record_changed",
    )
    return inspected["records"][0], binding


def _same_fields(price: PriceSnapshot, expected: dict[str, Any]) -> None:
    _require(
        all(_same(getattr(price.price_sku, k), v) for k, v in expected["sku"].items())
        and all(_same(getattr(price, k), v) for k, v in _price_values(expected).items()),
        "immutable_price_identity_mismatch",
    )


def _legacy(
    session: Session,
    old_id: int,
    plan: dict[str, Any],
    record: dict[str, Any],
    binding: dict[str, Any],
    selection: CatalogSelection,
) -> PriceSnapshot:
    price = session.get(PriceSnapshot, old_id)
    _require(price is not None, "legacy_price_missing")
    assert price is not None
    ev = price.evidence
    _require(
        ev is not None
        and ev.parser_rule == LEGACY_RULE
        and ev.evidence_type == "json_path"
        and ev.confidence == 1
        and ev.review_status in documents.ADMISSIBLE_EXTRACTION_STATES
        and ev.content_hash == digest(ev.excerpt),
        "unsupported_or_changed_legacy_evidence",
    )
    payload = decode_catalog_json(ev.excerpt.encode(), limit=8 * 1024 * 1024)
    _require(payload["rule_version"] == LEGACY_RULE, "unsupported_legacy_parser")
    _require(
        payload["catalog_record"] == record
        and ev.locator == record["price_locator"]
        and ev.snapshot_record_id == binding["snapshot_record_id"]
        and ev.source_document_id == binding["source_document_id"]
        and all(payload.get(k) == v for k, v in binding.items() if k != "registry_sha256")
        and all(payload.get(k) == v for k, v in plan["context"].items()),
        "legacy_catalog_identity_mismatch",
    )
    config = payload["promotion_config"]
    choices = [CatalogSelection.model_validate(s) for s in config["selections"]]
    _require(
        config["snapshot_id"] == binding["snapshot_record_id"]
        and [s for s in choices if s.sku == selection.sku] == [selection],
        "legacy_selection_mismatch",
    )
    expected = plan["rows"][0]
    _same_fields(price, expected)
    _require(
        payload["billing_unit"] == expected["sku"]["billing_unit"]
        and payload["billing_period"] == expected["price"]["billing_period"]
        and payload["tax_included"] is expected["sku"]["tax_included"]
        and payload["requires_all_tiers"] is True,
        "legacy_stored_semantics_mismatch",
    )
    peers = list(
        session.scalars(
            select(PriceSnapshot.id)
            .join(Evidence)
            .where(
                PriceSnapshot.price_sku_id == price.price_sku_id,
                Evidence.snapshot_record_id == ev.snapshot_record_id,
                Evidence.parser_rule == LEGACY_RULE,
            )
        )
    )
    _require(peers == [old_id], "ambiguous_or_partial_legacy_group")
    return price


def _successors(session: Session, old: PriceSnapshot, row: dict[str, Any]) -> list[int]:
    matches = list(
        session.scalars(
            select(PriceSnapshot)
            .join(Evidence)
            .where(
                PriceSnapshot.price_sku_id == old.price_sku_id,
                Evidence.snapshot_record_id == row["evidence"]["snapshot_record_id"],
                Evidence.locator == row["evidence"]["locator"],
            )
        )
    )
    new = [p for p in matches if p.id != old.id]
    _require(
        len(new) <= 1
        and all(
            p.evidence.parser_rule == documents.RULE
            and p.evidence.content_hash == row["evidence"]["content_hash"]
            for p in new
        ),
        "ambiguous_successor_or_competing_parser",
    )
    return [p.id for p in new]


class AWSPriceReplacementVerifier:
    """Mandatory live verifier, pinned to one explicit old ID and document plan.

    Current proof is available only for an exact v2 successor, never a legacy row.
    Historical proof ignores retired website policy and cannot grant eligibility.
    Parent resolution should obtain this document plan from the receipt's exact
    successor Evidence, not search for a cheaper/similar SKU.
    """

    def __init__(self, *, old_price_id: int, document_plan: dict[str, Any], raw_root: Path):
        _shape(old_price_id, document_plan)
        self.old_price_id = old_price_id
        self.document_plan = decode_catalog_json(canonical(document_plan).encode())
        self.raw_root = raw_root

    def __call__(
        self,
        session: Session,
        price_ids: tuple[int, ...],
        *,
        purpose: lifecycle.Purpose,
        now: datetime,
    ) -> lifecycle.VerifiedPriceGroup:
        _clean(session, now)
        selection, expected = _shape(self.old_price_id, self.document_plan)
        record, binding = _catalog_facts(
            session,
            self.document_plan,
            selection,
            raw_root=self.raw_root,
            now=now,
        )
        old = _legacy(session, self.old_price_id, self.document_plan, record, binding, selection)
        policies: tuple[lifecycle.EvidenceBinding, ...] = ()
        if purpose == "historical":
            _require(price_ids == (old.id,), "unsupported_historical_group")
            price = old
            dependency = {"catalog": binding, "context": self.document_plan["context"]}
        else:
            _require(purpose == "current", "unsupported_proof_purpose")
            ids = _successors(session, old, expected)
            _require(len(ids) == 1 and price_ids == tuple(ids), "exact_successor_required")
            documents.validate_document_catalog_prices(
                session,
                self.document_plan,
                price_snapshot_ids=ids,
                raw_root=self.raw_root,
                as_of=now,
            )
            successor = session.get(PriceSnapshot, ids[0])
            assert successor is not None
            price = successor
            policies = tuple(
                lifecycle.EvidenceBinding(
                    evidence_id=ref["evidence_id"],
                    state_sha256=lifecycle.evidence_fingerprint(session, ref["evidence_id"]),
                )
                for ref in self.document_plan["policy_evidence_references"]
            )
            dependency = {"document_plan_sha256": self.document_plan["plan_sha256"]}
        _require(price.price_sku_id == old.price_sku_id, "successor_sku_mismatch")
        return lifecycle.VerifiedPriceGroup(
            verifier_version=RULE,
            purpose=purpose,
            checked_at=now,
            price_sku_id=old.price_sku_id,
            catalog_snapshot_id=binding["snapshot_record_id"],
            catalog_sha256=binding["raw_sha256"],
            catalog_sku=record["sku"],
            offer_code=record["rate_code"].split(".")[1],
            catalog_scope_sha256=digest(
                canonical(
                    {
                        "selection": selection.model_dump(mode="json"),
                        "product_attributes": record["product_attributes"],
                        "effective_from": record["effective_from"],
                    }
                )
            ),
            catalog_rate_codes=(record["rate_code"],),
            complete_tier_group=True,
            authorized_catalog=True,
            current_policy_verified=purpose == "current",
            dependency_sha256=digest(
                canonical({"rule": RULE, "old_price_id": old.id, **dependency})
            ),
            policy_evidence=policies,
            rates=(
                lifecycle.VerifiedRate(
                    price_id=price.id,
                    row_sha256=lifecycle.price_fingerprint(session, price.id),
                    rate_code=record["rate_code"],
                    locator=record["price_locator"],
                    raw_unit=record["unit"],
                    unit_price=record["unit_price"],
                    minimum_quantity=record["begin_range"],
                    maximum_quantity=None if record["end_range"] == "Inf" else record["end_range"],
                ),
            ),
        )


def aws_replacement_disposition(
    session: Session,
    price: PriceSnapshot,
    raw_root: Path,
    now: datetime | None = None,
) -> lifecycle.PriceDisposition:
    """Live receipt-bound consumption hook; unactivated v2 rows are blocked.

    The exact dedicated receipt determines both IDs. The document plan is rebuilt
    from that successor's persisted derivation config, never from a SKU search or
    another available price. Every call rechecks registry, raw and policy inputs.
    """
    # Reading an expired ORM id can autoflush unrelated pending writes.
    identity = inspect(price).identity
    price_id = identity[0] if identity is not None else 0
    try:
        at = now or datetime.now(UTC)
        _clean(session, at)
        _require(price_id > 0, "persisted_price_identity_required")
        receipts = [
            receipt
            for receipt in lifecycle._ledger(session)
            if price_id in (*lifecycle._ids(receipt.plan.old), *lifecycle._ids(receipt.plan.new))
        ]
        _require(len(receipts) == 1, "missing_or_ambiguous_replacement_receipt")
        receipt = receipts[0]
        old_ids, new_ids = lifecycle._ids(receipt.plan.old), lifecycle._ids(receipt.plan.new)
        _require(
            len(old_ids) == len(new_ids) == 1
            and old_ids[0] in SUPPORTED
            and receipt.plan.old.verifier_version == RULE
            and receipt.plan.new.verifier_version == RULE,
            "unsupported_aws_replacement_receipt",
        )
        successor = session.get(PriceSnapshot, new_ids[0])
        _require(
            successor is not None
            and successor.evidence.parser_rule == documents.RULE
            and successor.evidence.content_hash == digest(successor.evidence.excerpt),
            "missing_or_changed_document_successor",
        )
        assert successor is not None
        payload = decode_catalog_json(successor.evidence.excerpt.encode(), limit=8 * 1024 * 1024)
        config = payload["derivation_config"]
        _require(
            set(config) == {"snapshot_id", "selections", "policy_references", "max_age_days"},
            "unsupported_successor_derivation_config",
        )
        plan = documents.prepare_document_catalog_plan(
            session,
            snapshot_id=config["snapshot_id"],
            selections=[CatalogSelection.model_validate(s) for s in config["selections"]],
            policy_references=[
                documents.DocumentPolicyReference.model_validate(ref)
                for ref in config["policy_references"]
            ],
            raw_root=raw_root,
            as_of=at,
            max_age_days=config["max_age_days"],
        )
        verifier = AWSPriceReplacementVerifier(
            old_price_id=old_ids[0],
            document_plan=plan,
            raw_root=raw_root,
        )
        return lifecycle.resolve_price(session, price_id, verifier=verifier, now=at)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ArithmeticError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, lifecycle.LifecycleConflict)
            else "aws_replacement_proof_failed"
        )
        return lifecycle.PriceDisposition(
            price_id=price_id, status="blocked", diagnostics=(reason,)
        )


def prepare_aws_price_replacement(
    session: Session,
    *,
    old_price_id: int,
    document_plan: dict[str, Any],
    raw_root: Path,
    as_of: datetime,
) -> AWSReplacementPlan:
    """Read-only plan; no successor insertion or automatic legacy selection."""
    _clean(session, as_of)
    _shape(old_price_id, document_plan)
    verified = documents.validate_document_catalog_plan(
        session,
        document_plan,
        raw_root=raw_root,
        as_of=as_of,
    )
    verifier = AWSPriceReplacementVerifier(
        old_price_id=old_price_id,
        document_plan=verified,
        raw_root=raw_root,
    )
    proof = verifier(session, (old_price_id,), purpose="historical", now=as_of)
    receipts = lifecycle._for_sku(lifecycle._ledger(session), proof.price_sku_id)
    plan = AWSReplacementPlan(
        old_price_id=old_price_id,
        old_row_sha256=proof.rates[0].row_sha256,
        document_plan=verified,
        expected_lifecycle_sha256=lifecycle._ledger_hash(receipts),
        plan_sha256="0" * 64,
    )
    return plan.model_copy(update={"plan_sha256": _hash(plan)})


def apply_aws_price_replacement(
    session: Session,
    plan: AWSReplacementPlan,
    *,
    expected_plan_sha256: str,
    raw_root: Path,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Default read-only; savepoint encloses successor facts plus lifecycle audit.

    Caller owns outer commit/rollback. Retry the saved plan with its pinned hash;
    a lock failure requires rollback/retry of the complete caller transaction.
    """
    at = now or datetime.now(UTC)
    _clean(session, at)
    plan = AWSReplacementPlan.model_validate(plan.model_dump(mode="python"))
    _require(
        plan.plan_sha256 == expected_plan_sha256 == _hash(plan), "replacement_plan_hash_mismatch"
    )
    _shape(plan.old_price_id, plan.document_plan)
    if apply:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            driver = connection.connection.driver_connection
            if not driver.in_transaction:  # type: ignore[union-attr]
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            _require(connection.dialect.name == "postgresql", "unsupported_write_dialect")

    def execute() -> dict[str, Any]:
        old = session.get(PriceSnapshot, plan.old_price_id)
        _require(old is not None, "legacy_price_missing")
        assert old is not None
        if apply:
            session.execute(
                select(PriceSKU).where(PriceSKU.id == old.price_sku_id).with_for_update()
            ).all()
            session.execute(
                select(PriceSnapshot).where(PriceSnapshot.id == old.id).with_for_update()
            ).all()
        _clean(session, at)
        _require(
            lifecycle.price_fingerprint(session, old.id) == plan.old_row_sha256,
            "legacy_row_cas_conflict",
        )
        documents.validate_document_catalog_plan(
            session, plan.document_plan, raw_root=raw_root, as_of=at
        )
        verifier = AWSPriceReplacementVerifier(
            old_price_id=old.id,
            document_plan=plan.document_plan,
            raw_root=raw_root,
        )
        verifier(session, (old.id,), purpose="historical", now=at)
        row = plan.document_plan["rows"][0]
        ids = _successors(session, old, row)
        receipts = lifecycle._for_sku(lifecycle._ledger(session), old.price_sku_id)
        existing = [r for r in receipts if old.id in lifecycle._ids(r.plan.old)]
        result: dict[str, Any] = {
            "rule_version": RULE,
            "plan_sha256": plan.plan_sha256,
            "old_price_id": old.id,
            "new_price_id": None,
            "applied": apply,
            "created": False,
            "transaction_committed": False,
            "evidence_created": 0,
            "price_snapshots_created": 0,
            "price_skus_created": 0,
            "scope": "internal_reference_only",
            "customer_eligible": False,
            "price_approval": False,
            "complete_tco": False,
            "customer_payable_tax": "unknown",
        }
        if existing:
            _require(
                len(existing) == 1 and lifecycle._ids(existing[0].plan.new) == tuple(ids),
                "replacement_idempotency_conflict",
            )
            replay = lifecycle.apply_replacement(
                session, existing[0].plan, verifier=verifier, apply=apply, now=at
            )
            return {**result, "new_price_id": ids[0], "lifecycle": replay.model_dump(mode="json")}
        _require(
            lifecycle._ledger_hash(receipts) == plan.expected_lifecycle_sha256,
            "lifecycle_cas_conflict",
        )
        _require(not ids, "successor_without_replacement_receipt")
        # Detect conflicting orphan Evidence even in read-only preview.
        before = evidence_row(session, row["evidence"])
        if not apply:
            return {**result, "status": "replacement_planned", "prices_planned": 1}
        evidence = evidence_row(session, row["evidence"], apply=True)
        assert evidence is not None
        successor = PriceSnapshot(
            **_price_values(row),
            price_sku_id=old.price_sku_id,
            evidence_id=evidence.id,
            created_at=at,
        )
        session.add(successor)
        session.flush()
        lifecycle_plan = lifecycle.prepare_replacement(
            session,
            [old.id],
            [successor.id],
            verifier=verifier,
            now=at,
        )
        _require(
            lifecycle_plan.expected_lifecycle_sha256 == plan.expected_lifecycle_sha256,
            "lifecycle_cas_conflict",
        )
        applied = lifecycle.apply_replacement(
            session, lifecycle_plan, verifier=verifier, apply=True, now=at
        )
        return {
            **result,
            "status": "replacement_appended_pending_caller_commit",
            "new_price_id": successor.id,
            "created": True,
            "evidence_created": int(before is None),
            "price_snapshots_created": 1,
            "lifecycle": applied.model_dump(mode="json"),
        }

    if apply:
        with session.begin_nested():
            return execute()
    with session.no_autoflush:
        return execute()
