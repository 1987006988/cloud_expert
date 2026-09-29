from cloud_expert.database.models.decision import DecisionScenario
from cloud_expert.database.models.mapping import MappingCandidate, MappingRuleSet
from cloud_expert.decision.pipeline import _target_market_block


def test_cross_market_mapping_is_hard_blocked_before_scoring() -> None:
    candidate = MappingCandidate(rule_set=MappingRuleSet(market_mode="cross_market"))
    scenario = DecisionScenario(market_mode="international")
    assert _target_market_block(None, scenario, candidate) == (
        "cross_market_mapping_in_normal_decision"
    )
