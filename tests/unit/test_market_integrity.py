from sqlalchemy.orm import Session

from cloud_expert.market.validation import scan_market_integrity
from tests.fixtures.synthetic_data import load_synthetic_fixture


def test_integrity_scan_preserves_unknown_scope_and_reports_no_customer_exposure(
    session: Session,
) -> None:
    load_synthetic_fixture(session)
    result = scan_market_integrity(session)
    assert result["counts"]["source_partition_missing"] == 1
    assert result["counts"]["region_partition_missing"] == 1
    assert result["counts"]["price_region_partition_missing"] == 1
    assert result["customer_exposure_detected"] is False
    assert result["internal_remediation_required"] is True
