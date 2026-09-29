"""Synthetic-only composition tests using the existing real parser adapters."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.models.tco import (
    CostCalculationRun,
    CostLineItem,
    PricingScenario,
    TCOResult,
)
from cloud_expert.pricing import aliyun_promotion, extraction, huawei_promotion
from cloud_expert.pricing.policy_costs import PolicyContext
from cloud_expert.pricing.scoped_tco import (
    OPTIONAL_DIMENSIONS,
    CostInput,
    ScopedECSConfig,
    compose_scoped_tco,
    persist_scoped_tco,
    scoped_tco_result_currently_complete,
    snapshot_scope,
)
from tests.unit.test_aliyun_price_promotion import inputs  # noqa: F401
from tests.unit.test_huawei_price_promotion import component_input, promotion_input  # noqa: F401
from tests.unit.test_policy_costs import (  # noqa: F401
    isolated_policy_registry,
    make_policy,
    policy_registry_entries,
)


def make_config(session, prices, support, ip=None):
    first = prices[0].price_sku
    huawei = first.provider.code == "huawei_cloud"
    context = PolicyContext(
        provider_id=first.provider_id,
        product_id=first.product_id,
        provider_code=first.provider.code,
        partition=first.region.cloud_partition.partition_code,
        region=first.region.code,
        duration_hours="730" if huawei else "720",
        support_plan="basic",
        eip_binding="bound" if huawei else "not_deployed",
        eip_bound_hours="730" if huawei else "0",
    )
    costs = [
        CostInput(
            dimension=dimension,
            treatment="price",
            quantity=price.minimum_quantity,
            unit=price.price_sku.billing_unit,
            rationale="Synthetic explicit workload; not a customer requirement",
            price_snapshot_id=price.id,
            evidence_sha256=price.evidence.content_hash,
            expected_price_scope=snapshot_scope(session, price),
        )
        for dimension, price in zip(("compute", "system_disk", "outbound"), prices, strict=True)
    ]
    costs.append(
        CostInput(
            dimension="support",
            treatment="policy_zero",
            quantity="1",
            unit="scenario",
            rationale="Synthetic basic support plan selected for entire period",
            evidence_id=support.id,
            evidence_sha256=support.content_hash,
            policy_code="huawei_basic_support" if huawei else "aliyun_basic_support",
        )
    )
    if ip:
        costs.append(
            CostInput(
                dimension="ip_holding",
                treatment="policy_zero",
                quantity="1",
                unit="scenario",
                rationale="Synthetic EIP remains bound throughout the explicit period",
                evidence_id=ip.id,
                evidence_sha256=ip.content_hash,
                policy_code="huawei_bound_eip",
            )
        )
    else:
        costs.append(
            CostInput(
                dimension="ip_holding",
                treatment="missing",
                quantity="1",
                unit="scenario",
                rationale="Official evidence for public IP holding charges is missing",
            )
        )
    costs.extend(
        CostInput(
            dimension=dimension,
            treatment="not_applicable",
            quantity="0",
            unit="scenario",
            rationale=f"Synthetic bounded architecture does not deploy {dimension}; not a fee claim",
        )
        for dimension in OPTIONAL_DIMENSIONS
    )
    return ScopedECSConfig(
        scenario_code="synthetic_scoped_ecs",
        scenario_version="synthetic-v1",
        name="Synthetic ECS bounded costs",
        context=context,
        price_basis="official_bounded_quote" if huawei else "catalog_reference",
        disk_capacity="100",
        disk_capacity_unit="GB" if huawei else "GiB",
        outbound_gb="100",
        outbound_cap_mbps="5" if huawei else None,
        architecture_description="Synthetic single VM and system disk with explicitly listed traffic; not resilient production architecture",
        enabled_optional_costs=(),
        costs=tuple(costs),
    )


@pytest.fixture
def scoped_inputs(session, component_input):  # noqa: F811
    quotes, units, tax, sizes, store = component_input
    prices = []
    for i in range(3):
        result = huawei_promotion.promote_quote(
            session,
            quotes[i],
            units[1 if i == 2 else 0],
            tax,
            size_evidence_id=sizes[1] if i == 1 else sizes[0] if i == 2 else None,
            root=store.raw_data_dir,
        )
        prices.append(session.get(PriceSnapshot, result["price_snapshot_id"]))
    support, _ = make_policy(
        session, store, prices[0].price_sku.provider_id, "huawei_cloud_basic_support_policy"
    )
    ip, _ = make_policy(
        session, store, prices[0].price_sku.provider_id, "huawei_cloud_eip_binding_policy"
    )
    config = make_config(session, prices, support, ip)
    session.commit()
    return config, store, prices


def replace_cost(config, dimension, **changes):
    data = config.model_dump(mode="json")
    cost = next(row for row in data["costs"] if row["dimension"] == dimension)
    cost.update(changes)
    return ScopedECSConfig.model_validate(data)


def test_complete_internal_scope_with_exact_prices_and_no_approval(session, scoped_inputs):
    config, store, _ = scoped_inputs
    before = session.scalar(select(func.count()).select_from(CostCalculationRun))
    report = compose_scoped_tco(session, config, root=store.raw_data_dir)
    assert report["completeness_status"] == "complete"
    assert Decimal(report["total"]) == Decimal("1251")
    assert report["tax_amount"] is None
    assert report["comparability_status"] == "needs_review"
    assert not report["model_approved"] and not report["customer_eligible"]
    assert session.scalar(select(func.count()).select_from(CostCalculationRun)) == before
    assert not session.new and not session.dirty
    policy = next(line for line in report["line_items"] if line["dimension"] == "ip_holding")
    assert policy["evidence_id"] is not None and policy["price_snapshot_id"] is None
    na = next(line for line in report["line_items"] if line["dimension"] == "migration")
    assert na["unit_price"] is None and na["amount"] == "0"


def test_missing_cost_cannot_be_a_zero_or_total(session, scoped_inputs):
    config, store, _ = scoped_inputs
    config = replace_cost(
        config,
        "support",
        treatment="missing",
        evidence_id=None,
        evidence_sha256=None,
        policy_code=None,
    )
    report = compose_scoped_tco(session, config, root=store.raw_data_dir)
    assert report["total"] is None and report["missing_price_count"] == 1
    assert Decimal(report["known_subtotal"]) == Decimal("1251")
    assert report["completeness_status"] == "missing_price"


@pytest.mark.parametrize(
    "mutation",
    [
        "hours",
        "disk",
        "unit",
        "cap",
        "price_scope",
        "hash",
        "policy_dimension",
        "policy_hash",
        "price_id",
        "region",
        "extrapolate",
        "category",
        "docs_as_pricing",
    ],
)
def test_fail_closed_on_wrong_input_scope(session, scoped_inputs, mutation):
    config, store, prices = scoped_inputs
    data = config.model_dump(mode="json")
    if mutation == "hours":
        data["context"]["duration_hours"] = "731"
    elif mutation == "disk":
        data["disk_capacity"] = "101"
    elif mutation == "unit":
        data["disk_capacity_unit"] = "GiB"
    elif mutation == "cap":
        data["outbound_cap_mbps"] = "10"
    elif mutation == "price_scope":
        data["costs"][0]["expected_price_scope"]["request"]["resource_spec"] = "another-sku"
    elif mutation == "hash":
        data["costs"][0]["evidence_sha256"] = "0" * 64
    elif mutation in {"policy_dimension", "policy_hash"}:
        policy = next(c for c in data["costs"] if c["dimension"] == "support")
        policy["policy_code" if mutation == "policy_dimension" else "evidence_sha256"] = (
            "huawei_bound_eip" if mutation == "policy_dimension" else "0" * 64
        )
    elif mutation == "price_id":
        data["costs"][0]["price_snapshot_id"] = 999999
    elif mutation == "region":
        data["context"]["region"] = "cn-synthetic-wrong"
    elif mutation == "extrapolate":
        data["costs"][0]["quantity"] = "1460"
    elif mutation == "category":
        prices[0].price_sku.charge_category = "traffic"
    else:
        prices[0].evidence.source_document.source_type = "documentation"
    with pytest.raises(ValueError):
        compose_scoped_tco(session, ScopedECSConfig.model_validate(data), root=store.raw_data_dir)


@pytest.mark.parametrize(
    "mutation",
    [
        "omit",
        "duplicate",
        "core_na",
        "deployed_na",
        "no_rationale",
        "unknown_field",
        "zero_price",
        "unknown_optional",
    ],
)
def test_inventory_must_disclose_every_required_cost(scoped_inputs, mutation):
    config, _, _ = scoped_inputs
    data = config.model_dump(mode="json")
    if mutation == "omit":
        data["costs"].pop()
    elif mutation == "duplicate":
        data["costs"].append(data["costs"][0])
    elif mutation == "core_na":
        data["costs"][0] = {
            "dimension": "compute",
            "treatment": "not_applicable",
            "quantity": "0",
            "unit": "scenario",
            "rationale": "Cannot hide a required compute cost",
        }
    elif mutation == "deployed_na":
        data["enabled_optional_costs"] = ["load_balancer"]
    elif mutation == "no_rationale":
        data["costs"][-1]["rationale"] = ""
    elif mutation == "unknown_field":
        data["customer_eligible"] = True
    elif mutation == "zero_price":
        data["costs"][0]["quantity"] = "0"
    else:
        data["enabled_optional_costs"] = ["undisclosed_service"]
    with pytest.raises(ValueError):
        ScopedECSConfig.model_validate(data)


def test_explicit_deployed_optional_cost_stays_missing(session, scoped_inputs):
    config, store, _ = scoped_inputs
    data = config.model_dump(mode="json")
    data["enabled_optional_costs"] = ["load_balancer"]
    row = next(c for c in data["costs"] if c["dimension"] == "load_balancer")
    row.update(
        treatment="missing",
        quantity="1",
        rationale="Synthetic architecture deploys a balancer with no official price yet",
    )
    report = compose_scoped_tco(
        session, ScopedECSConfig.model_validate(data), root=store.raw_data_dir
    )
    assert report["total"] is None
    assert report["missing_price_count"] == 1


def test_persist_idempotence_preserves_history_and_caller_rollback(session, scoped_inputs):
    config, store, _ = scoped_inputs
    before = session.scalar(select(func.count()).select_from(CostCalculationRun))
    first = persist_scoped_tco(session, config, root=store.raw_data_dir)
    assert first["created"]
    second = persist_scoped_tco(session, config, root=store.raw_data_dir)
    assert not second["created"] and second["run_id"] == first["run_id"]
    result = session.scalar(select(TCOResult).where(TCOResult.run_id == first["run_id"]))
    assert scoped_tco_result_currently_complete(session, result, root=store.raw_data_dir)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(CostCalculationRun)) == before
    assert (
        session.scalar(
            select(PricingScenario).where(PricingScenario.scenario_code == config.scenario_code)
        )
        is None
    )


def test_new_version_instead_of_overwriting_scenario(session, scoped_inputs):
    config, store, _ = scoped_inputs
    first = persist_scoped_tco(session, config, root=store.raw_data_dir)
    session.commit()
    altered = config.model_copy(
        update={"architecture_description": "Changed synthetic explicit architecture description"}
    )
    with pytest.raises(ValueError, match="immutable scenario"):
        persist_scoped_tco(session, altered, root=store.raw_data_dir)
    session.rollback()
    second = persist_scoped_tco(
        session,
        altered.model_copy(update={"scenario_version": "synthetic-v2"}),
        root=store.raw_data_dir,
    )
    assert second["scenario_id"] != first["scenario_id"]
    original = session.get(PricingScenario, first["scenario_id"])
    assert (
        original.workload_profile["scoped_ecs_config"]["architecture_description"]
        == config.architecture_description
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "amount",
        "assumptions",
        "result",
        "run_hash",
        "scenario",
        "evidence",
        "policy_raw",
        "duplicate",
        "cutoff",
        "future_run",
        "late",
    ],
)
def test_consumption_revalidates_all_inputs_not_just_saved_status(session, scoped_inputs, mutation):
    config, store, prices = scoped_inputs
    report = persist_scoped_tco(session, config, root=store.raw_data_dir)
    result = session.scalar(select(TCOResult).where(TCOResult.run_id == report["run_id"]))
    now = None
    if mutation == "amount":
        result.run.line_items[0].amount = Decimal("0")
    elif mutation == "assumptions":
        result.run.line_items[0].assumptions = {"customer_eligible": True}
    elif mutation == "result":
        result.total = Decimal("0")
    elif mutation == "run_hash":
        result.run.content_hash = "0" * 64
    elif mutation == "scenario":
        result.scenario.assumptions = {"customer_eligible": True}
    elif mutation == "evidence":
        prices[0].evidence.review_status = "rejected"
    elif mutation == "policy_raw":
        policy = next(c for c in config.costs if c.dimension == "support")
        evidence = session.get(Evidence, policy.evidence_id)
        from cloud_expert.database.models.snapshot import SnapshotRecord

        snapshot = session.get(SnapshotRecord, evidence.snapshot_record_id)
        (store.raw_data_dir / snapshot.storage_path).write_bytes(b"altered")
    elif mutation == "duplicate":
        line = result.run.line_items[0]
        result.run.line_items.append(
            CostLineItem(
                provider_id=line.provider_id,
                product_id=line.product_id,
                dimension=line.dimension,
                tax_status="tax_unknown",
            )
        )
    elif mutation == "cutoff":
        result.run.price_snapshot_cutoff = datetime.now(UTC) - timedelta(days=90)
    elif mutation == "future_run":
        result.run.started_at = datetime.now(UTC) + timedelta(days=1)
        result.run.price_snapshot_cutoff = result.run.started_at
        result.run.completed_at = result.run.started_at
    else:
        now = datetime.now(UTC) + timedelta(days=15)
    assert not scoped_tco_result_currently_complete(
        session, result, root=store.raw_data_dir, now=now
    )


def test_stale_price_fails_before_any_insertion(session, scoped_inputs):
    config, store, _ = scoped_inputs
    before = session.scalar(select(func.count()).select_from(PricingScenario))
    with pytest.raises(ValueError, match="fresh"):
        persist_scoped_tco(
            session, config, root=store.raw_data_dir, now=datetime.now(UTC) + timedelta(days=15)
        )
    assert session.scalar(select(func.count()).select_from(PricingScenario)) == before


def test_aliyun_720_hour_catalog_keeps_missing_ip_and_no_equivalence(session, inputs):  # noqa: F811
    ids, tax, store = inputs
    extraction.persist_price_records(
        session, [aliyun_promotion.extract_catalog_record(session, eid, tax) for eid in ids]
    )
    prices = list(
        session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.evidence.has(parser_rule=aliyun_promotion.RULE))
            .order_by(PriceSnapshot.id)
        )
    )
    support, _ = make_policy(
        session, store, prices[0].price_sku.provider_id, "aliyun_basic_support_policy"
    )
    config = make_config(session, prices, support)
    report = compose_scoped_tco(session, config, root=store.raw_data_dir)
    assert report["total"] is None and report["missing_price_count"] == 1
    assert Decimal(report["known_subtotal"]) == Decimal("2111")
    assert report["config"]["context"]["duration_hours"] == "720"
    assert report["config"]["disk_capacity_unit"] == "GiB"
    assert report["config"]["price_basis"] == "catalog_reference"
    assert report["compute_identity"]["compute_sku_code"] == "ecs.g6.xlarge"
    assert report["compute_identity"]["vcpu"] == 4
    assert report["compute_identity"]["memory_value"] == "16"
    assert report["compute_identity"]["memory_unit"] == "GiB"
    assert report["compute_identity"]["cpu_architecture"] is None
    session.commit()
    persisted = persist_scoped_tco(session, config, root=store.raw_data_dir)
    scenario = session.get(PricingScenario, persisted["scenario_id"])
    assert scenario.workload_profile["compute_instance_hours"] == "720"
    assert scenario.workload_profile["compute_sku_code"] == "ecs.g6.xlarge"
    assert scenario.workload_profile["memory_unit"] == "GiB"
    assert "memory_gb" not in scenario.workload_profile
    assert scenario.assumptions["duration_origin"] == "labeled_30_day_catalog_column"
    assert (
        scenario.assumptions["duration_comparison_policy"]
        == "No cross-provider duration normalization"
    )
    with pytest.raises(ValueError):
        compose_scoped_tco(
            session,
            config.model_copy(
                update={
                    "context": config.context.model_copy(update={"duration_hours": Decimal(730)})
                }
            ),
            root=store.raw_data_dir,
        )


def test_aliyun_fixed_ipv4_policy_closes_only_the_recorded_gap(session, inputs):  # noqa: F811
    ids, tax, store = inputs
    extraction.persist_price_records(
        session, [aliyun_promotion.extract_catalog_record(session, eid, tax) for eid in ids]
    )
    prices = list(
        session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.evidence.has(parser_rule=aliyun_promotion.RULE))
            .order_by(PriceSnapshot.id)
        )
    )
    support, _ = make_policy(
        session, store, prices[0].price_sku.provider_id, "aliyun_basic_support_policy"
    )
    ip, _ = make_policy(
        session, store, prices[0].price_sku.provider_id, "aliyun_ecs_fixed_ipv4_billing_policy"
    )
    config = replace_cost(
        make_config(session, prices, support),
        "ip_holding",
        treatment="policy_zero",
        evidence_id=ip.id,
        evidence_sha256=ip.content_hash,
        policy_code="aliyun_instance_fixed_ipv4",
    )
    report = compose_scoped_tco(session, config, root=store.raw_data_dir)
    assert report["completeness_status"] == "complete"
    assert not report["customer_eligible"]
    bad = config.model_dump(mode="json")
    bad["context"].update(eip_binding="bound", eip_bound_hours="720")
    with pytest.raises(ValueError, match="independent EIP"):
        compose_scoped_tco(session, ScopedECSConfig.model_validate(bad), root=store.raw_data_dir)


def test_persistence_rejects_pending_unrelated_writes(session, scoped_inputs):
    config, store, prices = scoped_inputs
    prices[0].unit_price = Decimal("99")
    with pytest.raises(ValueError, match="clean coordinator"):
        persist_scoped_tco(session, config, root=store.raw_data_dir)


def test_mid_write_failure_can_be_fully_rolled_back(session, scoped_inputs, monkeypatch):
    config, store, _ = scoped_inputs
    count = session.scalar(select(func.count()).select_from(PricingScenario))
    original_flush = session.flush

    def fail_after_run_insert(*args, **kwargs):
        writing_run = any(isinstance(item, CostCalculationRun) for item in session.new)
        original_flush(*args, **kwargs)
        if writing_run:
            raise RuntimeError("Synthetic persistence failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, "flush", fail_after_run_insert)
        with pytest.raises(RuntimeError, match="Synthetic"):
            persist_scoped_tco(session, config, root=store.raw_data_dir)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(PricingScenario)) == count
    assert (
        session.scalar(
            select(PricingScenario).where(PricingScenario.scenario_code == config.scenario_code)
        )
        is None
    )


def test_existing_run_cannot_be_silently_repaired_in_place(session, scoped_inputs):
    config, store, _ = scoped_inputs
    report = persist_scoped_tco(session, config, root=store.raw_data_dir)
    run = session.get(CostCalculationRun, report["run_id"])
    run.content_hash = "0" * 64
    session.commit()
    with pytest.raises(ValueError, match="immutable scoped run"):
        persist_scoped_tco(session, config, root=store.raw_data_dir)
    assert run.content_hash == "0" * 64


def test_quote_sku_is_evidenced_without_inventing_memory_or_architecture(session, scoped_inputs):
    config, store, prices = scoped_inputs
    assert prices[0].price_sku.sku_id is None
    report = persist_scoped_tco(session, config, root=store.raw_data_dir)
    scenario = session.get(PricingScenario, report["scenario_id"])
    profile = scenario.workload_profile
    assert profile["compute_sku_code"] == "c6.xlarge.4.linux"
    proof = profile["compute_sku_evidence"]
    origin_id = snapshot_scope(session, prices[0])["derived"]["quote_evidence_id"]
    origin = session.get(Evidence, origin_id)
    assert proof["evidence_id"] == origin.id
    assert proof["source_document_id"] == origin.source_document_id
    assert proof["snapshot_record_id"] == origin.snapshot_record_id
    assert proof["content_hash"] == origin.content_hash
    assert proof["proven_fields"] == ["compute_sku_code"]
    assert profile["vcpu"] is profile["memory_value"] is profile["memory_unit"] is None
    assert profile["cpu_architecture"] is None
    assert profile["disk_capacity_unit"] == "GB"
    assert profile["compute_instance_hours"] == "730"
    assert prices[0].price_sku.sku_id is None
    result = session.scalar(select(TCOResult).where(TCOResult.run_id == report["run_id"]))
    assert scoped_tco_result_currently_complete(session, result, root=store.raw_data_dir)


def test_missing_compute_price_cannot_reuse_an_unvalidated_sku(session, scoped_inputs):
    config, store, _ = scoped_inputs
    config = replace_cost(
        config,
        "compute",
        treatment="missing",
        price_snapshot_id=None,
        evidence_sha256=None,
        expected_price_scope=None,
    )
    report = persist_scoped_tco(session, config, root=store.raw_data_dir)
    scenario = session.get(PricingScenario, report["scenario_id"])
    profile = scenario.workload_profile
    assert profile["compute_sku_code"] is profile["compute_sku_evidence"] is None
    assert scenario.assumptions["duration_origin"] == "explicit_internal_scenario_assumption"
    assert report["total"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("compute_sku_code", "unrelated.sku"),
        ("memory_unit", "GB"),
        ("cpu_architecture", "x86_64"),
        ("compute_instance_hours", "720"),
        ("compute_sku_evidence", {"evidence_id": 999999}),
    ],
)
def test_compute_identity_cannot_be_tampered_at_consumption(session, scoped_inputs, key, value):
    config, store, _ = scoped_inputs
    report = persist_scoped_tco(session, config, root=store.raw_data_dir)
    result = session.scalar(select(TCOResult).where(TCOResult.run_id == report["run_id"]))
    result.scenario.workload_profile = {**result.scenario.workload_profile, key: value}
    assert not scoped_tco_result_currently_complete(session, result, root=store.raw_data_dir)


def test_legacy_scenario_is_not_backfilled_in_place(session, scoped_inputs):
    config, store, _ = scoped_inputs
    old_profile = {"compute_instance_hours": "730", "scope": "Synthetic legacy general scenario"}
    legacy = PricingScenario(
        scenario_code=config.scenario_code,
        scenario_version=config.scenario_version,
        name=config.name,
        market_mode="domestic",
        billing_period="monthly",
        target_currency="CNY",
        workload_profile=old_profile,
        assumptions={"synthetic": True},
        status="active",
    )
    session.add(legacy)
    session.commit()
    with pytest.raises(ValueError, match="immutable scenario"):
        persist_scoped_tco(session, config, root=store.raw_data_dir)
    session.rollback()
    new = persist_scoped_tco(
        session,
        config.model_copy(update={"scenario_version": "synthetic-identity-v2"}),
        root=store.raw_data_dir,
    )
    assert new["scenario_id"] != legacy.id
    assert legacy.workload_profile == old_profile
    assert "compute_sku_code" not in legacy.workload_profile
