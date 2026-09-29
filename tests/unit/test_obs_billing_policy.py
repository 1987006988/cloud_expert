"""Synthetic policy fragments exercise extraction, not current price assertions."""

import pytest

from cloud_expert.pricing.obs_billing import extract_billing_clauses

SYNTHETIC_HTML = """
<p>合成测试：以小时为单位，每小时整点结算。</p>
<p>合成测试：费用结算的最小时长为1小时。</p>
<p>合成测试：如果需要计算每小时产生的费用，使用1/24与1/30。仅供参考。</p>
"""


def test_billing_policy_never_proves_tariff_or_api_period() -> None:
    clauses = extract_billing_clauses(SYNTHETIC_HTML)
    assert len(clauses) == 3
    assert all(item["not_current_price_tariff"] for item in clauses)
    assert all(item["api_size_quote_time_basis_proven"] is False for item in clauses)
    assert len({item["clause_code"] for item in clauses}) == 3


@pytest.mark.parametrize(
    "removed", ["以小时为单位，每小时整点结算", "费用结算的最小时长为1小时", "1/30", "仅供参考"]
)
def test_billing_clause_change_fails_closed(removed: str) -> None:
    with pytest.raises(ValueError):
        extract_billing_clauses(SYNTHETIC_HTML.replace(removed, ""))


def test_navigation_or_script_is_not_billing_evidence() -> None:
    with pytest.raises(ValueError):
        extract_billing_clauses(
            SYNTHETIC_HTML.replace("<p>", "<script>").replace("</p>", "</script>")
        )
