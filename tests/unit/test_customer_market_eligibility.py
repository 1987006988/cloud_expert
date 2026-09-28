from types import SimpleNamespace

from cloud_expert.evidence_packages.builder import _customer_eligible_mapping


def _candidate(market: str, status: str = "approved", blockers: list[str] | None = None):
    return SimpleNamespace(
        review_status="human_reviewed",
        candidate_status=status,
        blocking_reasons=blockers or [],
        rule_set=SimpleNamespace(market_mode=market),
    )


def test_cross_market_mapping_cannot_be_customer_eligible_even_when_human_reviewed() -> None:
    assert not _customer_eligible_mapping(_candidate("cross_market"))


def test_blocked_or_unapproved_mapping_cannot_be_customer_eligible() -> None:
    assert not _customer_eligible_mapping(_candidate("domestic", blockers=["scope_mismatch"]))
    assert not _customer_eligible_mapping(_candidate("domestic", status="not_comparable"))


def test_approved_same_market_mapping_can_pass_this_guard() -> None:
    assert _customer_eligible_mapping(_candidate("domestic"))
