from cloud_expert.market.mapping_integrity import relationship_market_status


def test_relationship_mode_uses_both_product_markets() -> None:
    assert relationship_market_status("domestic", "domestic", "domestic") == "compatible"
    assert relationship_market_status("domestic", "international", "cross_market") == "cross_market"
    assert (
        relationship_market_status("domestic", "domestic", "cross_market") == "rule_market_mismatch"
    )
    assert (
        relationship_market_status("domestic", "international", "domestic")
        == "mislabeled_cross_market"
    )
    assert relationship_market_status("unknown", "domestic", "domestic") == "unknown"
