from unittest.mock import Mock

import pytest
from sqlalchemy import event

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.provider import Provider
from cloud_expert.pricing import consumption
from cloud_expert.pricing.price_lifecycle import PriceDisposition
from tests.unit.test_aws_price_replacement import fixture_data
from tests.unit.test_market_guards import _price_snapshot


@pytest.mark.parametrize("rule", [None, "renamed_to_skip_validation", "aws_unknown_v9"])
def test_unknown_aws_parser_cannot_avoid_deep_validation(rule, monkeypatch, session):
    price = _price_snapshot()
    price.evidence.parser_rule = rule
    verifier = Mock(return_value=True)
    monkeypatch.setattr(consumption, "aws_catalog_price_valid", verifier)
    assert consumption.is_aws_price(price)
    assert not consumption.aws_price_current(session, price)
    verifier.assert_not_called()


@pytest.mark.parametrize("approved", [True, False])
def test_registered_rule_calls_actual_verifier(approved, monkeypatch, session):
    price = _price_snapshot()
    price.evidence.parser_rule = consumption.AWS_CATALOG_RULE
    verifier = Mock(return_value=approved)
    monkeypatch.setattr(consumption, "aws_catalog_price_valid", verifier)
    monkeypatch.setattr(consumption, "quarantine_disposition", Mock(return_value=None))
    monkeypatch.setattr(consumption, "expired_history_disposition", Mock(return_value=None))
    assert consumption.aws_price_current(session, price) is approved
    assert verifier.call_args.args == (session, price)


def test_aws_derivation_without_loaded_provider_still_requires_verification(session):
    price = _price_snapshot()
    price.price_sku.provider = None
    price.evidence.parser_rule = "aws_unknown_v9"
    assert consumption.is_aws_price(price)
    assert not consumption.aws_price_current(session, price)


@pytest.mark.parametrize("rule", [consumption.AWS_DOCUMENT_RULE, consumption.AWS_CATALOG_RULE])
@pytest.mark.parametrize("status", ["current", "superseded", "blocked"])
def test_replacement_requires_current_receipt_not_just_valid_document(
    rule, status, monkeypatch, session
):
    price = _price_snapshot()
    price.id = 13 if rule == consumption.AWS_CATALOG_RULE else 19
    price.evidence.parser_rule = rule
    disposition = PriceDisposition(price_id=price.id, status=status)
    verifier = Mock(return_value=disposition)
    legacy = Mock(return_value=True)
    monkeypatch.setattr(consumption, "aws_replacement_disposition", verifier)
    monkeypatch.setattr(consumption, "aws_catalog_price_valid", legacy)
    monkeypatch.setattr(consumption, "quarantine_disposition", Mock(return_value=None))
    monkeypatch.setattr(consumption, "expired_history_disposition", Mock(return_value=None))
    assert consumption.aws_price_current(session, price) is (status == "current")
    assert consumption.aws_price_disposition(session, price) == disposition
    assert verifier.call_args.args == (session, price)
    legacy.assert_not_called()


@pytest.mark.parametrize("valid", [True, False])
def test_nonreplacement_disposition_keeps_unverified_history_blocked(valid, monkeypatch, session):
    price = _price_snapshot()
    price.id = 100
    price.evidence.parser_rule = consumption.AWS_CATALOG_RULE
    monkeypatch.setattr(consumption, "aws_catalog_price_valid", Mock(return_value=valid))
    monkeypatch.setattr(consumption, "quarantine_disposition", Mock(return_value=None))
    monkeypatch.setattr(consumption, "expired_history_disposition", Mock(return_value=None))
    result = consumption.aws_price_disposition(session, price)
    assert result.status == ("current" if valid else "blocked")
    assert result.current_price_id == (100 if valid else None)
    assert not result.customer_eligible


@pytest.mark.parametrize("status", ["quarantined", "blocked"])
def test_quarantine_or_corrupt_receipt_prevents_validator_fallback(status, monkeypatch, session):
    price = _price_snapshot()
    disposition = PriceDisposition(price_id=7, status=status)
    verifier = Mock(return_value=True)
    monkeypatch.setattr(consumption, "quarantine_disposition", Mock(return_value=disposition))
    monkeypatch.setattr(consumption, "aws_catalog_price_valid", verifier)
    assert not consumption.aws_price_current(session, price)
    assert consumption.aws_price_disposition(session, price) == disposition
    verifier.assert_not_called()


def test_real_quarantine_is_unconsumable(session, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tests.unit.test_price_quarantine import apply, plan, seed

    data = seed(session, tmp_path, monkeypatch)
    proposal = plan(session, data)
    apply(session, data, proposal)
    session.commit()
    monkeypatch.setattr(consumption, "get_settings", lambda: SimpleNamespace(raw_data_dir=tmp_path))
    for price_id in data["ids"]:
        price = session.get(PriceSnapshot, price_id)
        assert consumption.aws_price_disposition(session, price).status == "quarantined"
        assert not consumption.aws_price_current(session, price)


@pytest.mark.parametrize("status", ["expired_history", "blocked"])
def test_expiry_or_corrupt_expiry_prevents_current_price_fallback(status, monkeypatch, session):
    from cloud_expert.pricing.aws_expired_history import ExpiryDisposition

    price = _price_snapshot()
    disposition = ExpiryDisposition(price_id=19, status=status)
    verifier = Mock(side_effect=AssertionError("Expired history cannot request current approval"))
    monkeypatch.setattr(consumption, "quarantine_disposition", Mock(return_value=None))
    monkeypatch.setattr(consumption, "expired_history_disposition", Mock(return_value=disposition))
    monkeypatch.setattr(consumption, "aws_replacement_disposition", verifier)
    monkeypatch.setattr(consumption, "aws_catalog_price_valid", verifier)
    assert not consumption.aws_price_current(session, price)
    result = consumption.aws_price_disposition(session, price)
    assert result.status == status and result.current_price_id is None
    assert not result.customer_eligible
    verifier.assert_not_called()


@pytest.mark.parametrize("operation", ["classify", "current", "disposition"])
def test_expired_orm_object_cannot_flush_pending_changes(operation, session, tmp_path, monkeypatch):
    fixture_data(session, tmp_path, monkeypatch)
    price = session.get(PriceSnapshot, 13)
    assert price is not None
    session.expire(price)
    pending = Provider(code="synthetic_pending", name="Synthetic", display_name="Synthetic")
    session.add(pending)
    flushes = []

    def forbidden_flush(*args):
        flushes.append(True)
        raise AssertionError("read-only validation attempted autoflush")

    event.listen(session, "before_flush", forbidden_flush)
    try:
        if operation == "classify":
            assert consumption.is_aws_price(price)
        elif operation == "current":
            assert not consumption.aws_price_current(session, price)
        else:
            result = consumption.aws_price_disposition(session, price)
            assert result.price_id == 13
            assert result.status == "blocked"
            assert result.diagnostics == ("clean_session_required",)
        assert not flushes
        assert pending in session.new
    finally:
        event.remove(session, "before_flush", forbidden_flush)
        session.rollback()
