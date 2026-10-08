import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from cloud_expert.pricing.price_lifecycle import PriceDisposition


@pytest.fixture
def reporter(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("validate_price_evidence")


def _report(monkeypatch, reporter, statuses, *, evidence_links=None):
    session = MagicMock()
    prices = [SimpleNamespace(id=index + 1) for index in range(len(statuses))]
    session.scalars.side_effect = [prices, [], []]
    count = len(prices)
    session.scalar.side_effect = [
        count,
        count if evidence_links is None else evidence_links,
        count,
        0,
    ]
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(reporter, "SessionLocal", factory)
    verifier = Mock(
        side_effect=[
            PriceDisposition(price_id=price.id, status=status)
            for price, status in zip(prices, statuses, strict=True)
        ]
    )
    monkeypatch.setattr(reporter, "aws_price_disposition", verifier)
    result = reporter.validate_price_evidence()
    assert verifier.call_count == count
    session.commit.assert_not_called()
    return result


def test_superseded_history_is_visible_and_never_current(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["superseded", "current"])
    assert result["valid"]
    assert result["price_snapshots"] == 2
    assert result["historical_superseded_aws_prices"] == [1]
    assert result["currently_unusable_aws_prices"] == [1]
    assert result["invalid_aws_catalog_prices"] == []
    assert len(result["aws_price_dispositions"]) == 2


def test_unresolved_price_still_blocks_with_other_valid_replacements(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["blocked", "superseded", "current"])
    assert not result["valid"]
    assert result["invalid_aws_catalog_prices"] == [1]
    assert result["currently_unusable_aws_prices"] == [1, 2]
    assert result["historical_superseded_aws_prices"] == [2]


def test_historical_link_integrity_remains_required(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["superseded", "current"], evidence_links=1)
    assert not result["valid"]
    assert "one or more PriceSnapshot rows do not resolve to Evidence" in result["errors"]


def test_no_price_rows_cannot_pass(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, [])
    assert not result["valid"]
    assert result["price_evidence_completeness"] == 0


def test_verified_quarantine_is_retained_but_not_a_current_price(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["quarantined", "current"])
    assert result["valid"]
    assert result["historical_quarantined_aws_prices"] == [1]
    assert result["currently_unusable_aws_prices"] == [1]
    assert result["active_price_rows"] == 1
    assert not result["full_product_price_coverage_claimed"]


def test_quarantine_cannot_hide_missing_historical_links(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["quarantined", "current"], evidence_links=1)
    assert not result["valid"]


def test_all_quarantined_cannot_pass_an_empty_active_price_set(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["quarantined", "quarantined"])
    assert not result["valid"]
    assert result["active_price_rows"] == 0


def test_verified_expiry_is_visible_but_never_price_coverage(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["expired_history", "expired_history", "current"])
    assert result["valid"]
    assert result["historical_expired_aws_prices"] == [1, 2]
    assert result["currently_unusable_aws_prices"] == [1, 2]
    assert result["active_price_rows"] == 1
    assert not result["full_product_price_coverage_claimed"]


def test_expiry_does_not_hide_corrupt_history(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["expired_history", "blocked", "current"])
    assert not result["valid"]
    assert result["invalid_aws_catalog_prices"] == [2]
    assert result["historical_expired_aws_prices"] == [1]


def test_expiry_does_not_hide_broken_evidence_links(monkeypatch, reporter):
    result = _report(monkeypatch, reporter, ["expired_history", "current"], evidence_links=1)
    assert not result["valid"]


@pytest.mark.parametrize("statuses", [["expired_history"], ["expired_history", "quarantined"]])
def test_only_historical_prices_cannot_pass(monkeypatch, reporter, statuses):
    result = _report(monkeypatch, reporter, statuses)
    assert not result["valid"]
    assert result["active_price_rows"] == 0
    assert "no active price rows remain after historical disposition" in result["errors"]
