"""Real isolated PostgreSQL transactions; synthetic prices, raw files and policy only."""

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.review import ModelReviewFinding
from cloud_expert.pricing import price_lifecycle as life
from cloud_expert.pricing import price_quarantine as quarantine
from tests.integration import test_postgres_price_lifecycle as pg_lifecycle
from tests.unit.test_official_catalog import NOW
from tests.unit.test_price_quarantine import counts, seed

pytestmark = pytest.mark.postgres
isolated_pricing_engine = pg_lifecycle.isolated_pricing_engine


def _plan(session, data, ids=None):
    return quarantine.prepare_price_quarantine(
        session, data["ids"] if ids is None else ids, raw_root=data["root"], now=NOW
    )


def _apply(session, data, plan):
    return quarantine.apply_price_quarantine(
        session,
        plan,
        expected_plan_sha256=plan.plan_sha256,
        raw_root=data["root"],
        apply=True,
        now=NOW,
    )


def _fingerprints(session, data):
    return {price_id: life.price_fingerprint(session, price_id) for price_id in data["ids"]}


def _expect_lock_timeout(session, data, plan):
    session.execute(text("SET LOCAL lock_timeout = '200ms'"))
    with pytest.raises(OperationalError) as error:
        _apply(session, data, plan)
    assert (
        getattr(error.value.orig, "sqlstate", getattr(error.value.orig, "pgcode", None)) == "55P03"
    )
    session.rollback()


def test_postgres_quarantine_atomic_rollback_and_idempotence(
    isolated_pricing_engine,
    tmp_path,
    monkeypatch,
):
    with Session(isolated_pricing_engine) as session:
        data = seed(session, tmp_path, monkeypatch)
        before, fingerprints = counts(session), _fingerprints(session, data)
        plan = _plan(session, data)
        result = _apply(session, data, plan)
        assert result["created"] and not result["transaction_committed"]
        session.rollback()
        assert counts(session) == before
        assert _fingerprints(session, data) == fingerprints
        first = _apply(session, data, plan)
        session.commit()
        repeated = _apply(session, data, plan)
        session.commit()
        assert not repeated["created"] and repeated["receipt_sha256"] == first["receipt_sha256"]
        assert tuple(b - a for a, b in zip(before, counts(session), strict=True)) == (
            0,
            0,
            0,
            1,
            3,
            3,
            3,
        )
        assert _fingerprints(session, data) == fingerprints
        assert not first["consumable"] and not first["customer_eligible"]
        assert not first["price_validated"] and first["approvals_granted"] == 0
        for price_id in data["ids"]:
            disposition = quarantine.quarantine_disposition(
                session, session.get(PriceSnapshot, price_id), data["root"], NOW
            )
            assert disposition is not None and disposition.status == "quarantined"
            assert disposition.current_price_id is None and not disposition.customer_eligible


def test_postgres_quarantine_partial_append_rolls_back(
    isolated_pricing_engine,
    tmp_path,
    monkeypatch,
):
    with Session(isolated_pricing_engine) as session:
        data = seed(session, tmp_path, monkeypatch)
        before, fingerprints = counts(session), _fingerprints(session, data)
        plan = _plan(session, data)
        inserted = []

        def fail_after_first_finding(mapper, connection, target):
            inserted.append(target.id)
            raise RuntimeError("synthetic failure after first quarantine finding")

        event.listen(ModelReviewFinding, "after_insert", fail_after_first_finding)
        try:
            with pytest.raises(RuntimeError, match="synthetic failure"):
                _apply(session, data, plan)
        finally:
            event.remove(ModelReviewFinding, "after_insert", fail_after_first_finding)
        assert len(inserted) == 1
        # The failed savepoint must not leave audit fragments for the caller to commit.
        session.commit()
        assert counts(session) == before
        assert _fingerprints(session, data) == fingerprints
        assert _apply(session, data, plan)["created"]
        session.rollback()
        assert counts(session) == before


def test_postgres_quarantine_competing_connection_locks_then_retries(
    isolated_pricing_engine,
    tmp_path,
    monkeypatch,
):
    with Session(isolated_pricing_engine) as first, Session(isolated_pricing_engine) as second:
        data = seed(first, tmp_path, monkeypatch)
        before, fingerprints = counts(first), _fingerprints(first, data)
        first_plan, second_plan = _plan(first, data), _plan(second, data)
        assert first_plan.plan_sha256 == second_plan.plan_sha256
        result = _apply(first, data, first_plan)
        _expect_lock_timeout(second, data, second_plan)
        first.commit()
        retried = _apply(second, data, second_plan)
        second.commit()
        assert not retried["created"] and retried["receipt_sha256"] == result["receipt_sha256"]
        assert tuple(b - a for a, b in zip(before, counts(second), strict=True)) == (
            0,
            0,
            0,
            1,
            3,
            3,
            3,
        )
        assert _fingerprints(second, data) == fingerprints


def test_postgres_quarantine_competing_plans_reject_stale_audit(
    isolated_pricing_engine,
    tmp_path,
    monkeypatch,
):
    with Session(isolated_pricing_engine) as first, Session(isolated_pricing_engine) as second:
        data = seed(first, tmp_path, monkeypatch)
        before, fingerprints = counts(first), _fingerprints(first, data)
        first_plan = _plan(first, data, [data["first"]])
        second_plan = _plan(second, data, data["storage_ids"])
        _apply(first, data, first_plan)
        # Disjoint target rows must still serialize the shared quarantine audit CAS.
        _expect_lock_timeout(second, data, second_plan)
        first.commit()
        with pytest.raises(life.LifecycleConflict, match="quarantine_audit_cas_conflict"):
            _apply(second, data, second_plan)
        second.commit()
        assert tuple(b - a for a, b in zip(before, counts(second), strict=True)) == (
            0,
            0,
            0,
            1,
            1,
            1,
            1,
        )
        assert _fingerprints(second, data) == fingerprints
