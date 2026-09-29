"""Synthetic lifecycle proofs only: no business database, cloud fact or approval."""

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.model_review_workflow import (
    ModelReviewAssignment,
    ModelReviewAuditEvent,
)
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.review import ModelReviewFinding, ModelReviewRun
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.pricing import price_lifecycle as life

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
CATALOG = {
    "synthetic_only": True,
    "rates": [
        {"rate": "synthetic.offer.tier1", "price": "0.2", "begin": "0", "end": "100"},
        {"rate": "synthetic.offer.tier2", "price": "0.1", "begin": "100", "end": None},
    ],
}


def _snapshot(session, root, owner, name, raw, kind):
    path = root / f"{name}.bin"
    path.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    doc = SourceDocument(
        provider_id=owner.id,
        title="Synthetic lifecycle fixture only",
        source_type=kind,
        url=f"https://example.invalid/synthetic/{name}",
        cloud_partition="synthetic",
        authority_level="unknown",
        content_hash=digest,
        storage_path=path.name,
        is_current=True,
        captured_at=NOW - timedelta(hours=1),
    )
    session.add(doc)
    session.flush()
    snapshot = SnapshotRecord(
        source_document_id=doc.id,
        source_id=f"synthetic_{name}",
        content_hash=digest,
        storage_path=path.name,
        manifest_path=f"{name}.manifest.json",
        content_type="application/json",
        content_length_bytes=len(raw),
        captured_at=doc.captured_at,
        is_current=True,
        change_status="first_seen",
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _seed(session, root):
    owner = Provider(
        code="synthetic", name="Synthetic", display_name="Synthetic", provider_type="fixture"
    )
    category = ProductCategory(code="synthetic", name="Synthetic")
    session.add_all([owner, category])
    session.flush()
    partition = CloudPartition(
        provider_id=owner.id,
        partition_code="synthetic",
        partition_name="Synthetic",
        market_mode="international",
        is_active=True,
    )
    product = Product(
        provider_id=owner.id,
        category_id=category.id,
        code="synthetic",
        official_name="Synthetic only",
        display_name="Synthetic only",
        market_mode="international",
    )
    session.add_all([partition, product])
    session.flush()
    region = Region(
        provider_id=owner.id,
        code="synthetic",
        name="Synthetic",
        country_code="US",
        market_mode="international",
        cloud_partition_id=partition.id,
        is_active=True,
    )
    session.add(region)
    session.flush()
    sku = PriceSKU(
        provider_id=owner.id,
        product_id=product.id,
        region_id=region.id,
        provider_price_code="synthetic:catalog:sku",
        charge_category="storage",
        billing_mode="on_demand",
        billing_unit="synthetic-unit",
        currency="USD",
        tax_included=False,
    )
    session.add(sku)
    session.flush()
    catalog = _snapshot(session, root, owner, "catalog", json.dumps(CATALOG).encode(), "pricing")
    policy = _snapshot(
        session, root, owner, "policy", b'{"synthetic_policy_only":true}', "documentation"
    )
    proof = Evidence(
        source_document_id=policy.source_document_id,
        snapshot_record_id=policy.id,
        content_hash=policy.content_hash,
        excerpt="Synthetic policy only",
        locator="/synthetic",
        parser_rule="synthetic_policy",
        evidence_type="json_path",
        confidence=1.0,
        review_status="machine_extracted",
    )
    session.add(proof)
    session.flush()
    groups = []
    for generation in range(3):
        ids = []
        for index, rate in enumerate(CATALOG["rates"]):
            excerpt = json.dumps({"synthetic_generation": generation, "rate": rate})
            ev = Evidence(
                source_document_id=catalog.source_document_id,
                snapshot_record_id=catalog.id,
                content_hash=sha256(excerpt.encode()).hexdigest(),
                excerpt=excerpt,
                locator=f"/rates/{index}",
                parser_rule=f"synthetic_price_v{generation}",
                evidence_type="json_path",
                confidence=1.0,
                review_status="machine_extracted",
            )
            session.add(ev)
            session.flush()
            price = PriceSnapshot(
                price_sku_id=sku.id,
                evidence_id=ev.id,
                unit_price=Decimal(rate["price"]),
                minimum_quantity=Decimal(rate["begin"]),
                maximum_quantity=Decimal(rate["end"]) if rate["end"] else None,
                billing_period="usage",
                discount_type="list",
                captured_at=catalog.captured_at,
                effective_from=NOW - timedelta(days=1),
                effective_to=None,
                created_at=NOW + timedelta(seconds=generation),
                source_payload_path=catalog.storage_path,
            )
            session.add(price)
            session.flush()
            ids.append(price.id)
        groups.append(tuple(ids))
    session.commit()
    return {
        "root": root,
        "sku": sku.id,
        "catalog": catalog.id,
        "policy": policy.id,
        "policy_evidence": proof.id,
        "groups": groups,
    }


class Verifier:
    """An actual raw-checking SYNTHETIC adapter; never usable for real source data."""

    def __init__(self, data):
        self.data = data
        self.calls = []
        self.denied = set()
        self.licensed = True
        self.changed_dependency = False

    def __call__(self, session, price_ids, *, purpose, now):
        self.calls.append((price_ids, purpose, now))
        assert self.licensed, "synthetic license revoked"
        selected = session.get(PriceSnapshot, price_ids[0])
        assert selected is not None
        assert purpose != "current" or selected.id not in self.denied
        rows = list(
            session.scalars(
                select(PriceSnapshot)
                .join(Evidence)
                .where(
                    Evidence.parser_rule == selected.evidence.parser_rule,
                    PriceSnapshot.price_sku_id == self.data["sku"],
                )
                .order_by(PriceSnapshot.id)
            )
        )
        snapshot = session.get(SnapshotRecord, self.data["catalog"])
        raw = (self.data["root"] / snapshot.storage_path).read_bytes()
        assert sha256(raw).hexdigest() == snapshot.content_hash
        document = json.loads(raw)
        assert document["synthetic_only"] is True
        assert snapshot.is_current and snapshot.source_document.is_current
        assert now - life._utc(snapshot.captured_at) < timedelta(days=7)
        policy = session.get(SnapshotRecord, self.data["policy"])
        policies = ()
        if purpose == "current":
            assert (
                sha256((self.data["root"] / policy.storage_path).read_bytes()).hexdigest()
                == policy.content_hash
            )
            assert policy.is_current and policy.source_document.is_current
            policies = (
                life.EvidenceBinding(
                    evidence_id=self.data["policy_evidence"],
                    state_sha256=life.evidence_fingerprint(session, self.data["policy_evidence"]),
                ),
            )
        rates = []
        for row in rows:
            index = int(row.evidence.locator.rsplit("/", 1)[1])
            rate = document["rates"][index]
            assert row.evidence.content_hash == sha256(row.evidence.excerpt.encode()).hexdigest()
            assert (
                row.price_sku.currency == "USD" and row.price_sku.billing_unit == "synthetic-unit"
            )
            rates.append(
                life.VerifiedRate(
                    price_id=row.id,
                    row_sha256=life.price_fingerprint(session, row.id),
                    rate_code=rate["rate"],
                    locator=row.evidence.locator,
                    raw_unit="synthetic-raw-unit",
                    unit_price=rate["price"],
                    minimum_quantity=rate["begin"],
                    maximum_quantity=rate["end"],
                )
            )
        return life.VerifiedPriceGroup(
            verifier_version="synthetic-test-verifier-v1",
            purpose=purpose,
            checked_at=now,
            price_sku_id=self.data["sku"],
            catalog_snapshot_id=snapshot.id,
            catalog_sha256=snapshot.content_hash,
            catalog_sku="synthetic-sku",
            offer_code="synthetic.offer",
            catalog_scope_sha256="1" * 64,
            catalog_rate_codes=tuple(rate["rate"] for rate in document["rates"]),
            complete_tier_group=True,
            authorized_catalog=True,
            current_policy_verified=purpose == "current",
            dependency_sha256="3" * 64 if self.changed_dependency else "2" * 64,
            policy_evidence=policies,
            rates=tuple(rates),
        )


@pytest.fixture
def data(session, tmp_path):
    return _seed(session, tmp_path)


@pytest.fixture
def verifier(data):
    return Verifier(data)


def _plan(session, data, verifier, old=0, new=1):
    return life.prepare_replacement(
        session,
        data["groups"][old],
        data["groups"][new],
        verifier=verifier,
        now=NOW + timedelta(minutes=1),
    )


def _apply(session, plan, verifier, **kwargs):
    return life.apply_replacement(
        session, plan, verifier=verifier, now=NOW + timedelta(minutes=2), **kwargs
    )


def _resolve(session, price_id, verifier):
    return life.resolve_price(session, price_id, verifier=verifier, now=NOW + timedelta(minutes=3))


def _audit_counts(session):
    return tuple(
        session.scalar(select(func.count()).select_from(cls))
        for cls in (
            ModelReviewRun,
            ModelReviewFinding,
            ModelReviewAssignment,
            ModelReviewAuditEvent,
        )
    )


def _history(session):
    return [
        [life._row(row) for row in session.scalars(select(cls).order_by(cls.id))]
        for cls in (PriceSnapshot, PriceSKU, Evidence, SourceDocument, SnapshotRecord)
    ]


def test_dryrun_required_live_proof_and_no_history_writes(session, data, verifier):
    before = _history(session)
    plan = _plan(session, data, verifier)
    assert _audit_counts(session) == (0, 0, 0, 0)
    result = _apply(session, plan, verifier)
    assert not result.applied and not result.created and result.replaced_prices == 2
    assert result.transaction_committed is False and result.approvals_granted == 0
    assert _audit_counts(session) == (0, 0, 0, 0)
    assert _history(session) == before
    assert len(verifier.calls) == 4


def test_atomic_whole_group_append_and_current_superseded_dispositions(session, data, verifier):
    before = _history(session)
    plan = _plan(session, data, verifier)
    result = _apply(session, plan, verifier, apply=True)
    assert result.created and result.replaced_prices == 2
    session.commit()
    assert _audit_counts(session) == (1, 2, 2, 2)
    assert _history(session) == before
    for old, new in zip(*data["groups"][:2], strict=True):
        disposition = _resolve(session, old, verifier)
        assert disposition.status == "superseded"
        assert disposition.successor_id == disposition.current_price_id == new
        assert disposition.replacement_path == (old, new)
        assert not disposition.customer_eligible
        assert _resolve(session, new, verifier).status == "current"
    for event in session.scalars(select(ModelReviewAuditEvent)):
        assert event.source == life.EVENT_SOURCE and event.model_id is None
        assert event.new_status == "superseded" and event.previous_status is None
        assert event.downstream_rebuild_required
    from cloud_expert.model_review.migration import review_queue_integrity

    assert review_queue_integrity(session)["invalid_assignments"] == 0
    assert review_queue_integrity(session)["missing_assignments"] == 0


def test_idempotent_retry_still_rechecks_policy(session, data, verifier):
    plan = _plan(session, data, verifier)
    first = _apply(session, plan, verifier, apply=True)
    session.commit()
    count = len(verifier.calls)
    second = _apply(session, plan, verifier, apply=True)
    session.commit()
    assert not second.created and second.receipt_sha256 == first.receipt_sha256
    assert len(verifier.calls) > count and _audit_counts(session) == (1, 2, 2, 2)
    verifier.licensed = False
    with pytest.raises(life.LifecycleConflict, match="proof_verifier_failed"):
        _apply(session, plan, verifier, apply=True)
    session.rollback()
    assert _audit_counts(session) == (1, 2, 2, 2)


@pytest.mark.parametrize("failure", ["caller", "mid_write"])
def test_rollback_keeps_prices_and_removes_all_audit_rows(
    session, data, verifier, monkeypatch, failure
):
    before = _history(session)
    plan = _plan(session, data, verifier)
    if failure == "caller":
        _apply(session, plan, verifier, apply=True)
        session.rollback()
    else:
        original = life._append

        def broken(*args):
            original(*args)
            raise RuntimeError("synthetic failure after complete append")

        monkeypatch.setattr(life, "_append", broken)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            _apply(session, plan, verifier, apply=True)
        session.commit()
    assert _audit_counts(session) == (0, 0, 0, 0)
    assert _history(session) == before


@pytest.mark.parametrize(
    "mutation",
    ["price", "unit", "currency", "region", "provider", "effective_to", "policy", "dependency"],
)
def test_plan_cas_changes_fail_before_any_append(session, data, verifier, mutation):
    plan = _plan(session, data, verifier)
    row = session.get(PriceSnapshot, data["groups"][1][0])
    if mutation == "price":
        row.unit_price = Decimal("9")
    elif mutation == "unit":
        row.price_sku.billing_unit = "other-unit"
    elif mutation == "currency":
        row.price_sku.currency = "EUR"
    elif mutation == "region":
        row.price_sku.region.code = "other-region"
    elif mutation == "provider":
        row.price_sku.provider.code = "other-provider"
    elif mutation == "effective_to":
        row.effective_to = NOW
    elif mutation == "policy":
        session.get(Evidence, data["policy_evidence"]).review_status = "rejected"
    else:
        verifier.changed_dependency = True
    session.commit()
    with pytest.raises(life.LifecycleConflict):
        _apply(session, plan, verifier, apply=True)
    session.rollback()
    assert _audit_counts(session) == (0, 0, 0, 0)


@pytest.mark.parametrize("side", [0, 1])
def test_partial_tier_plan_is_rejected(session, data, verifier, side):
    groups = list(data["groups"][:2])
    groups[side] = groups[side][:1]
    with pytest.raises(life.LifecycleConflict, match="partial_group_request"):
        life.prepare_replacement(session, *groups, verifier=verifier, now=NOW)


@pytest.mark.parametrize("case", ["self", "backward", "missing"])
def test_no_self_backward_or_fabricated_successor(session, data, verifier, case):
    old, new = data["groups"][:2]
    if case == "self":
        new = old
    elif case == "backward":
        old, new = new, old
    else:
        new = (999999,)
    with pytest.raises(life.LifecycleConflict):
        life.prepare_replacement(session, old, new, verifier=verifier, now=NOW)
    assert _audit_counts(session) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "kind",
    [
        "none",
        "bool",
        "mapping",
        "old_time",
        "policy_false",
        "incomplete",
        "wrong_numeric",
        "wrong_rate",
        "unknown_schema",
        "unauthorized_catalog",
        "missing_policy",
        "excess_precision",
    ],
)
def test_no_permissive_verifier_or_unsupported_proof(session, data, verifier, kind):
    def bad(session, ids, *, purpose, now):
        if kind == "bool":
            return True
        if kind == "mapping":
            return {"valid": True}
        proof = verifier(session, ids, purpose=purpose, now=now)
        if kind == "old_time":
            return proof.model_copy(update={"checked_at": now - timedelta(seconds=1)})
        if kind == "policy_false":
            return proof.model_copy(update={"current_policy_verified": False})
        if kind == "incomplete":
            return proof.model_copy(update={"rates": proof.rates[:1]})
        if kind == "unknown_schema":
            return proof.model_copy(update={"schema_version": "unsupported_v99"})
        if kind == "unauthorized_catalog":
            return proof.model_copy(update={"authorized_catalog": False})
        if kind == "missing_policy":
            return proof.model_copy(update={"policy_evidence": ()})
        if kind == "excess_precision":
            return proof.model_copy(
                update={
                    "rates": (
                        proof.rates[0].model_copy(update={"unit_price": Decimal("0.123456789")}),
                        *proof.rates[1:],
                    )
                }
            )
        if kind == "wrong_numeric":
            return proof.model_copy(
                update={
                    "rates": (
                        proof.rates[0].model_copy(update={"unit_price": Decimal(99)}),
                        *proof.rates[1:],
                    )
                }
            )
        if purpose == "current":
            key = "rate_code" if kind == "wrong_rate" else "raw_unit"
            rate = proof.rates[0].model_copy(update={key: "not-the-original"})
            return proof.model_copy(update={"rates": (rate, *proof.rates[1:])})
        return proof

    check = None if kind == "none" else bad
    with pytest.raises(life.LifecycleConflict):
        _plan(session, data, check)
    assert _resolve(session, data["groups"][1][0], check).status == "blocked"


def test_different_raw_unit_cannot_replace_original_or_resolve_existing_receipt(
    session, data, verifier
):
    def changed_unit(session, ids, *, purpose, now):
        proof = verifier(session, ids, purpose=purpose, now=now)
        if purpose == "current":
            return proof.model_copy(
                update={
                    "rates": tuple(
                        rate.model_copy(update={"raw_unit": "other-raw-unit"})
                        for rate in proof.rates
                    )
                }
            )
        return proof

    with pytest.raises(life.LifecycleConflict, match="replacement_rate_mismatch:raw_unit"):
        _plan(session, data, changed_unit)
    _apply(session, _plan(session, data, verifier), verifier, apply=True)
    session.commit()
    assert _resolve(session, data["groups"][1][0], changed_unit).status == "blocked"


def test_unknown_legacy_parser_without_proven_successor_is_never_auto_linked(
    session, data, verifier
):
    legacy = data["groups"][0][0]
    session.get(PriceSnapshot, legacy).evidence.parser_rule = "unsupported_legacy"
    session.commit()

    def strict(session, ids, *, purpose, now):
        if session.get(PriceSnapshot, ids[0]).evidence.parser_rule == "unsupported_legacy":
            raise life.LifecycleConflict("unsupported_price_parser")
        return verifier(session, ids, purpose=purpose, now=now)

    result = _resolve(session, legacy, strict)
    assert result.status == "blocked" and result.diagnostics == ("unsupported_price_parser",)
    assert result.current_price_id is None and result.successor_id is None
    assert _resolve(session, data["groups"][1][0], strict).status == "current"
    with pytest.raises(life.LifecycleConflict, match="unsupported_price_parser"):
        _plan(session, data, strict)
    assert _audit_counts(session) == (0, 0, 0, 0)


def test_unrelated_sku_is_not_a_replacement_even_when_rates_match(session, data, verifier):
    original = session.get(PriceSKU, data["sku"])
    other = PriceSKU(
        **{
            column.name: getattr(original, column.name)
            for column in original.__table__.columns
            if column.name not in {"id", "created_at", "updated_at", "provider_price_code"}
        },
        provider_price_code="synthetic:unrelated:sku",
    )
    session.add(other)
    session.flush()
    other_id = other.id
    for price_id in data["groups"][1]:
        session.get(PriceSnapshot, price_id).price_sku_id = other_id
    session.commit()
    different_data = {**data, "sku": other_id}
    other_verifier = Verifier(different_data)

    def dispatched(session, ids, *, purpose, now):
        adapter = other_verifier if purpose == "current" else verifier
        return adapter(session, ids, purpose=purpose, now=now)

    with pytest.raises(life.LifecycleConflict, match="replacement_identity_mismatch:price_sku_id"):
        _plan(session, data, dispatched)
    assert _audit_counts(session) == (0, 0, 0, 0)


def test_proof_revoked_after_append_rolls_back_entire_tier_group(session, data, verifier):
    plan = _plan(session, data, verifier)
    before = _history(session)

    def revoked_after_append(session, ids, *, purpose, now):
        if session.scalar(select(func.count()).select_from(ModelReviewRun)):
            raise life.LifecycleConflict("synthetic_postwrite_dependency_revoked")
        return verifier(session, ids, purpose=purpose, now=now)

    with pytest.raises(life.LifecycleConflict, match="synthetic_postwrite_dependency_revoked"):
        _apply(session, plan, revoked_after_append, apply=True)
    session.commit()
    assert _audit_counts(session) == (0, 0, 0, 0) and _history(session) == before


def test_missing_price_is_structured_block_without_approval(session, verifier):
    result = _resolve(session, 999999, verifier)
    assert result.status == "blocked" and result.diagnostics == ("price_missing",)
    assert result.current_price_id is None and not result.customer_eligible


def test_no_receipt_current_price_still_requires_fresh_full_group_proof(session, data, verifier):
    row = data["groups"][0][0]
    assert _resolve(session, row, verifier).status == "current"
    count = len(verifier.calls)
    verifier.denied.add(row)
    assert _resolve(session, row, verifier).status == "blocked"
    assert len(verifier.calls) == count + 1


@pytest.mark.parametrize(
    "kind",
    [
        "catalog",
        "policy",
        "permission",
        "missing_successor",
        "price",
        "event",
        "finding",
        "assignment",
        "receipt",
        "missing_event",
    ],
)
def test_tamper_or_missing_dependency_blocks_old_and_new_no_fallback(session, data, verifier, kind):
    _apply(session, _plan(session, data, verifier), verifier, apply=True)
    session.commit()
    old, new = data["groups"][0][0], data["groups"][1][0]
    if kind in {"catalog", "policy"}:
        snapshot = session.get(SnapshotRecord, data[kind])
        path = data["root"] / snapshot.storage_path
        path.write_bytes(b"x" * path.stat().st_size)
    elif kind == "permission":
        verifier.licensed = False
    elif kind == "missing_successor":
        session.delete(session.get(PriceSnapshot, new))
    elif kind == "price":
        session.get(PriceSnapshot, new).unit_price = Decimal(3)
    elif kind == "event":
        event = session.scalar(select(ModelReviewAuditEvent))
        event.affected_records = [{"old_price_id": old, "new_price_id": old}]
    elif kind == "finding":
        session.scalar(select(ModelReviewFinding)).input_hash = "f" * 64
    elif kind == "assignment":
        session.scalar(select(ModelReviewAssignment)).review_state = "model_approved"
    elif kind == "receipt":
        run = session.scalar(select(ModelReviewRun))
        payload = copy.deepcopy(run.summary_json)
        payload["receipt_sha256"] = "f" * 64
        run.summary_json = payload
    else:
        session.delete(session.scalar(select(ModelReviewAuditEvent)))
    session.commit()
    result = _resolve(session, old, verifier)
    assert result.status == "blocked" and result.current_price_id is None
    assert _resolve(session, new, verifier).status == "blocked"


def test_two_successor_plans_cannot_fork_and_committed_receipt_is_unchanged(
    session, data, verifier
):
    a = _plan(session, data, verifier, new=1)
    b = _plan(session, data, verifier, new=2)
    _apply(session, a, verifier, apply=True)
    session.commit()
    before = session.scalar(select(ModelReviewRun)).summary_json
    with pytest.raises(life.LifecycleConflict, match="lifecycle_cas_conflict"):
        _apply(session, b, verifier, apply=True)
    session.rollback()
    assert session.scalar(select(ModelReviewRun)).summary_json == before
    assert _audit_counts(session) == (1, 2, 2, 2)


def test_multiple_replacement_generations_resolve_leaf_without_approving_retired_policy(
    session, data, verifier
):
    _apply(session, _plan(session, data, verifier), verifier, apply=True)
    session.commit()
    _apply(session, _plan(session, data, verifier, old=1, new=2), verifier, apply=True)
    session.commit()
    verifier.denied.update(data["groups"][1])
    for tier in (0, 1):
        ids = tuple(group[tier] for group in data["groups"])
        result = _resolve(session, ids[0], verifier)
        assert result.status == "superseded" and result.replacement_path == ids
        assert result.current_price_id == ids[-1] and len(result.receipt_sha256s) == 2
        assert _resolve(session, ids[-1], verifier).status == "current"


def test_forged_duplicate_edge_is_blocked_even_with_recomputed_hashes(session, data, verifier):
    a = _plan(session, data, verifier)
    b = _plan(session, data, verifier, new=2)
    _apply(session, a, verifier, apply=True)
    session.commit()
    # Simulate an out-of-protocol writer, not an authorized API operation.
    receipt = life.ReplacementReceipt(plan=b, applied_at=NOW, receipt_sha256="0" * 64)
    receipt = receipt.model_copy(update={"receipt_sha256": life._receipt_hash(receipt)})
    life._append(session, receipt)
    session.commit()
    assert "fork" in _resolve(session, data["groups"][0][0], verifier).diagnostics[0]


@pytest.mark.parametrize("kind", ["cycle", "self"])
def test_forged_cycle_or_self_edge_is_blocked_with_recomputed_hashes(session, data, verifier, kind):
    plan = _plan(session, data, verifier)
    _apply(session, plan, verifier, apply=True)
    session.commit()
    # Both malformed receipts contain existing rows, not fabricated price IDs.
    old = plan.new.model_copy(update={"purpose": "historical"})
    new = plan.old.model_copy(update={"purpose": "current"}) if kind == "cycle" else plan.new
    forged = plan.model_copy(update={"old": old, "new": new})
    forged = forged.model_copy(update={"plan_sha256": life._plan_hash(forged)})
    receipt = life.ReplacementReceipt(plan=forged, applied_at=NOW, receipt_sha256="0" * 64)
    receipt = receipt.model_copy(update={"receipt_sha256": life._receipt_hash(receipt)})
    life._append(session, receipt)
    session.commit()
    for group in data["groups"][:2]:
        for price_id in group:
            result = _resolve(session, price_id, verifier)
            assert result.status == "blocked" and result.current_price_id is None
            assert result.diagnostics == (
                "successor_not_newer" if kind == "cycle" else "self_replacement",
            )


def test_group_member_missing_audit_event_blocks_every_tier(session, data, verifier):
    _apply(session, _plan(session, data, verifier), verifier, apply=True)
    session.commit()
    event = session.scalars(
        select(ModelReviewAuditEvent).order_by(ModelReviewAuditEvent.id.desc())
    ).first()
    session.delete(event)
    session.commit()
    for group in data["groups"][:2]:
        for price_id in group:
            assert _resolve(session, price_id, verifier).status == "blocked"


def test_two_connection_sqlite_lock_then_retry_rejects_stale_fork(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'synthetic_lock.sqlite').as_posix()}",
        connect_args={"timeout": 0.01},
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as first, Session(engine) as second:
            data = _seed(first, tmp_path)
            verifier = Verifier(data)
            a = _plan(first, data, verifier)
            b = _plan(second, data, verifier, new=2)
            _apply(first, a, verifier, apply=True)
            with pytest.raises(OperationalError):
                _apply(second, b, verifier, apply=True)
            second.rollback()
            first.commit()
            with pytest.raises(life.LifecycleConflict, match="lifecycle_cas_conflict"):
                _apply(second, b, verifier, apply=True)
            second.rollback()
            assert _audit_counts(second) == (1, 2, 2, 2)
    finally:
        engine.dispose()
