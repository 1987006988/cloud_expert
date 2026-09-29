from cloud_expert.database.models.decision import DecisionScenario
from cloud_expert.database.models.tco import TCOResult
from cloud_expert.decision.pipeline import _tco_matches_scenario
from cloud_expert.pricing import scoped_tco
from cloud_expert.pricing.tco import tco_result_currently_complete
from tests.unit.test_huawei_price_promotion import component_input, promotion_input  # noqa: F401
from tests.unit.test_policy_costs import (  # noqa: F401
    isolated_policy_registry,
    policy_registry_entries,
)
from tests.unit.test_scoped_tco import (
    replace_cost,
    scoped_inputs,  # noqa: F401
)


def test_dispatch_revalidates_policy_and_exclusions(session, scoped_inputs, monkeypatch):  # noqa: F811
    config, store, _ = scoped_inputs
    report = scoped_tco.persist_scoped_tco(session, config, root=store.raw_data_dir)
    session.commit()
    result = session.query(TCOResult).filter_by(run_id=report["run_id"]).one()
    original = scoped_tco.scoped_tco_result_currently_complete
    monkeypatch.setattr(
        scoped_tco,
        "scoped_tco_result_currently_complete",
        lambda session, result: original(session, result, root=store.raw_data_dir),
    )
    assert tco_result_currently_complete(session, result)
    scenario = DecisionScenario(
        market_mode="domestic",
        country_code="CN",
        preferred_regions=[config.context.region],
        workload_profile={"monthly_hours": 730, "outbound_gb": 100},
    )
    assert _tco_matches_scenario(session, result, scenario)
    scenario.country_code = "US"
    assert not _tco_matches_scenario(session, result, scenario)
    scenario.country_code = "CN"
    scenario.workload_profile = {"monthly_hours": 720, "outbound_gb": 100}
    assert not _tco_matches_scenario(session, result, scenario)
    policy_line = next(line for line in result.run.line_items if line.dimension == "support")
    policy_line.evidence_id = None
    assert not tco_result_currently_complete(session, result)


def test_valid_partial_structure_does_not_mean_complete(session, scoped_inputs):  # noqa: F811
    config, store, _ = scoped_inputs
    config = replace_cost(
        config,
        "support",
        treatment="missing",
        evidence_id=None,
        evidence_sha256=None,
        policy_code=None,
    )
    report = scoped_tco.persist_scoped_tco(session, config, root=store.raw_data_dir)
    result = session.query(TCOResult).filter_by(run_id=report["run_id"]).one()
    assert result.total is None
    assert scoped_tco.scoped_tco_result_currently_valid(session, result, root=store.raw_data_dir)
    assert not scoped_tco.scoped_tco_result_currently_complete(
        session, result, root=store.raw_data_dir
    )
    policy_line = next(line for line in result.run.line_items if line.dimension == "ip_holding")
    policy_line.evidence_id = None
    assert not scoped_tco.scoped_tco_result_currently_valid(
        session, result, root=store.raw_data_dir
    )
