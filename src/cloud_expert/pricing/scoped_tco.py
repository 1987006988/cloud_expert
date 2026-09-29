"""Immutable, single-provider domestic ECS cost composition for explicit inputs.

No price selection by 'latest', no unit conversion, no SKU equivalence and no
approval side effects. Composition is read-only; persistence belongs to the
coordinator's transaction and never commits it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.models.tco import (
    CostCalculationRun,
    CostLineItem,
    PricingScenario,
    TCOResult,
)
from cloud_expert.pricing.aliyun_promotion import RULE as ALIYUN_RULE
from cloud_expert.pricing.aliyun_promotion import catalog_price_valid
from cloud_expert.pricing.freshness import price_snapshot_freshness
from cloud_expert.pricing.huawei_promotion import RULE as HUAWEI_RULE
from cloud_expert.pricing.huawei_promotion import bounded_quote_valid
from cloud_expert.pricing.policy_costs import PolicyContext, validate_zero_cost_policy

RULE_VERSION = "domestic_ecs_scoped_tco_v2"
CORE_DIMENSIONS = ("compute", "system_disk", "outbound", "ip_holding", "support")
OPTIONAL_DIMENSIONS = (
    "data_disk",
    "snapshot_backup",
    "load_balancer",
    "nat_gateway",
    "inter_region_transfer",
    "object_storage",
    "requests",
    "retrieval",
    "minimum_retention",
    "redundancy",
    "replication",
    "software_license",
    "operations",
    "migration",
)
REQUIRED_DIMENSIONS = CORE_DIMENSIONS + OPTIONAL_DIMENSIONS


class CostInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: str = Field(min_length=1, max_length=128)
    treatment: Literal["price", "policy_zero", "not_applicable", "missing"]
    quantity: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    unit: str = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=12)
    price_snapshot_id: int | None = Field(default=None, gt=0)
    evidence_id: int | None = Field(default=None, gt=0)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    policy_code: str | None = None
    expected_price_scope: dict[str, Any] | None = None

    @model_validator(mode="after")
    def check_evidence_kind(self) -> CostInput:
        if self.treatment == "price":
            if not all((self.price_snapshot_id, self.evidence_sha256, self.expected_price_scope)):
                raise ValueError(
                    "priced cost requires pinned snapshot, evidence hash and full scope"
                )
            if self.evidence_id is not None or self.policy_code is not None or self.quantity <= 0:
                raise ValueError("priced costs cannot carry policy evidence or zero quantities")
        elif self.treatment == "policy_zero":
            if not all((self.evidence_id, self.evidence_sha256, self.policy_code)):
                raise ValueError("zero fee requires explicit pinned policy evidence")
            if (
                self.price_snapshot_id
                or self.expected_price_scope
                or self.quantity != 1
                or self.unit != "scenario"
            ):
                raise ValueError("policy fees apply once to the whole explicit scenario")
        elif any(
            (
                self.price_snapshot_id,
                self.evidence_id,
                self.evidence_sha256,
                self.policy_code,
                self.expected_price_scope,
            )
        ):
            raise ValueError("missing/not-applicable cost cannot claim evidence or a price")
        if self.treatment == "not_applicable" and self.quantity != 0:
            raise ValueError("not-applicable quantity must be zero")
        return self


class ScopedECSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_code: str = Field(min_length=1, max_length=160)
    scenario_version: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    context: PolicyContext
    billing_period: Literal["explicit_hours"] = "explicit_hours"
    price_basis: Literal["official_bounded_quote", "catalog_reference"]
    disk_capacity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    disk_capacity_unit: Literal["GB", "GiB"]
    outbound_gb: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    outbound_cap_mbps: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    architecture_description: str = Field(min_length=20)
    enabled_optional_costs: tuple[str, ...]
    costs: tuple[CostInput, ...]
    purpose: Literal["internal_bounded_ecs_cost_research"] = "internal_bounded_ecs_cost_research"

    @model_validator(mode="after")
    def check_inventory(self) -> ScopedECSConfig:
        names = [cost.dimension for cost in self.costs]
        if len(names) != len(set(names)) or not set(REQUIRED_DIMENSIONS).issubset(names):
            raise ValueError("cost inventory has missing or duplicate dimensions")
        enabled = set(self.enabled_optional_costs)
        if len(enabled) != len(self.enabled_optional_costs) or enabled - (
            set(names) - set(CORE_DIMENSIONS)
        ):
            raise ValueError("enabled optional costs must appear exactly once in the inventory")
        for cost in self.costs:
            optional = cost.dimension not in CORE_DIMENSIONS
            if cost.treatment == "not_applicable" and (not optional or cost.dimension in enabled):
                raise ValueError("deployed/required architecture costs cannot be excluded")
            if optional and cost.dimension not in enabled and cost.treatment != "not_applicable":
                raise ValueError("optional cost deployment must be explicit")
        huawei = self.context.provider_code == "huawei_cloud"
        if (self.context.partition, self.price_basis, self.disk_capacity_unit) != (
            ("huawei_cn", "official_bounded_quote", "GB")
            if huawei
            else ("aliyun_public_cn", "catalog_reference", "GiB")
        ):
            raise ValueError("provider, price basis and capacity unit cannot be mixed")
        if huawei and self.outbound_cap_mbps is None:
            raise ValueError("Huawei traffic quote requires its explicit bandwidth cap")
        if not huawei and self.outbound_cap_mbps is not None:
            raise ValueError("catalog does not prove a bandwidth cap")
        return self


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def snapshot_scope(session: Session, price: PriceSnapshot) -> dict[str, Any]:
    """Expose exact input scope for explicit config, never infer equivalent SKUs."""
    data = json.loads(price.evidence.excerpt)
    if price.evidence.parser_rule == HUAWEI_RULE:
        quote = session.get(Evidence, data["quote_evidence_id"])
        if quote is None:
            raise ValueError("bounded quote evidence is missing")
        return {"derived": data, "request": json.loads(quote.excerpt)["request"]}
    if price.evidence.parser_rule == ALIYUN_RULE:
        return {"derived": data}
    raise ValueError("unsupported scoped price rule")


def _validate_product(session: Session, config: ScopedECSConfig) -> None:
    context = config.context
    product = session.get(Product, context.product_id)
    region = session.scalar(
        select(Region).where(
            Region.provider_id == context.provider_id, Region.code == context.region
        )
    )
    if (
        product is None
        or product.provider_id != context.provider_id
        or product.provider.code != context.provider_code
        or product.code != "ecs"
        or product.market_mode != "domestic"
        or region is None
        or region.country_code != "CN"
        or region.market_mode != "domestic"
        or region.cloud_partition is None
        or region.cloud_partition.partition_code != context.partition
        or region.cloud_partition.provider_id != context.provider_id
    ):
        raise ValueError("domestic ECS product/region/partition mismatch")


def _validate_quantity(config: ScopedECSConfig, cost: CostInput, scope: dict[str, Any]) -> None:
    expected = {
        "compute": (config.context.duration_hours, "instance-hour", "compute"),
        "system_disk": (
            config.context.duration_hours * config.disk_capacity,
            f"{config.disk_capacity_unit}-hour",
            "storage",
        ),
        "outbound": (config.outbound_gb, "GB", "traffic"),
    }
    if cost.dimension not in expected:
        raise ValueError("no bounded price adapter for this cost dimension; leave it missing")
    quantity, unit, _ = expected[cost.dimension]
    if (cost.quantity, cost.unit) != (quantity, unit):
        raise ValueError("cost quantity/unit differs from scenario; extrapolation is forbidden")
    if config.context.provider_code == "huawei_cloud":
        request = scope["request"]
        if cost.dimension == "compute":
            valid = (
                request["resource_type"] == "hws.resource.type.vm"
                and request["usage_factor"] == "Duration"
                and Decimal(str(request["usage_value"])) == config.context.duration_hours
            )
        elif cost.dimension == "system_disk":
            valid = (
                request["resource_type"] == "hws.resource.type.volume"
                and request["usage_factor"] == "Duration"
                and Decimal(str(request["usage_value"])) == config.context.duration_hours
                and Decimal(str(request["resource_size"])) == config.disk_capacity
                and request["size_measure_id"] == 17
            )
        else:
            valid = (
                request["usage_factor"] == "upflow"
                and Decimal(str(request["usage_value"])) == config.outbound_gb
                and Decimal(str(request["resource_size"])) == config.outbound_cap_mbps
                and request["size_measure_id"] == 15
            )
    else:
        assumptions = scope["derived"]["assumptions"]
        if cost.dimension == "compute":
            valid = Decimal(str(assumptions["duration_hours"])) == config.context.duration_hours
        elif cost.dimension == "system_disk":
            valid = (
                Decimal(str(assumptions["duration_hours"])) == config.context.duration_hours
                and Decimal(str(assumptions["capacity_gib"])) == config.disk_capacity
            )
        else:
            valid = Decimal(str(assumptions["usage_gb"])) == config.outbound_gb
    if not valid:
        raise ValueError("component request scope differs from the explicit architecture")


def _unknown_compute_identity() -> dict[str, Any]:
    return {
        "compute_sku_code": None,
        "compute_sku_evidence": None,
        "vcpu": None,
        "memory_value": None,
        "memory_unit": None,
        "cpu_architecture": None,
    }


def _compute_identity(
    session: Session, price: PriceSnapshot, scope: dict[str, Any]
) -> dict[str, Any]:
    """Called only after raw quote/catalog validation, never parse SKU-name ratios."""
    identity = _unknown_compute_identity()
    data = scope["derived"]
    huawei = price.evidence.parser_rule == HUAWEI_RULE
    origin_id = data["quote_evidence_id" if huawei else "catalog_evidence_id"]
    origin = session.get(Evidence, origin_id)
    if (
        origin is None
        or origin.review_status == "rejected"
        or origin.snapshot_record_id is None
        or origin.source_document_id != price.evidence.source_document_id
        or origin.snapshot_record_id != price.evidence.snapshot_record_id
        or origin.content_hash != hashlib.sha256(origin.excerpt.encode()).hexdigest()
        or data["supporting_hashes"].get(str(origin_id)) != origin.content_hash
    ):
        raise ValueError("compute identity source evidence is invalid")
    proven_fields = ["compute_sku_code"]
    if huawei:
        identity["compute_sku_code"] = scope["request"]["resource_spec"]
        if identity["compute_sku_code"] != data["resource_spec"]:
            raise ValueError("compute SKU differs from validated quote")
        # A resource code in a price request does not prove memory or CPU facts.
    else:
        row = json.loads(origin.excerpt)
        code, separator, period = data["resource_code"].partition(":")
        if (
            separator != ":"
            or period != "30days"
            or row["section"] != "compute"
            or row["headers"][:3] != ["\u5b9e\u4f8b\u89c4\u683c", "vCPUs", "\u5185\u5b58(GiB)"]
            or row["cells"][0] != f"\u901a\u7528\u578b {code}"
        ):
            raise ValueError("catalog does not prove the exact compute SKU and memory unit")
        vcpu, memory = int(row["cells"][1]), Decimal(row["cells"][2])
        if vcpu <= 0 or not memory.is_finite() or memory <= 0:
            raise ValueError("catalog compute dimensions must be explicit positive values")
        identity.update(
            compute_sku_code=code, vcpu=vcpu, memory_value=str(memory), memory_unit="GiB"
        )
        proven_fields.extend(["vcpu", "memory_value", "memory_unit"])
    identity["compute_sku_evidence"] = {
        "evidence_id": origin.id,
        "source_document_id": origin.source_document_id,
        "snapshot_record_id": origin.snapshot_record_id,
        "content_hash": origin.content_hash,
        "price_evidence_id": price.evidence_id,
        "price_snapshot_id": price.id,
        "proven_fields": proven_fields,
    }
    return identity


def _price_line(
    session: Session, config: ScopedECSConfig, cost: CostInput, *, root: Path | None, now: datetime
) -> dict[str, Any]:
    price = session.get(PriceSnapshot, cost.price_snapshot_id)
    if price is None:
        raise ValueError("selected price snapshot is missing")
    huawei = config.context.provider_code == "huawei_cloud"
    valid = (
        bounded_quote_valid(session, price, root=root)
        if huawei
        else catalog_price_valid(session, price)
    )
    sku = price.price_sku
    if (
        not valid
        or price.evidence.parser_rule != (HUAWEI_RULE if huawei else ALIYUN_RULE)
        or price.evidence.content_hash != cost.evidence_sha256
        or price.evidence.source_document.source_type != "pricing"
        or price_snapshot_freshness(price, now=now) != "fresh"
        or sku.provider_id != config.context.provider_id
        or sku.product_id != config.context.product_id
        or sku.region.code != config.context.region
        or sku.currency != "CNY"
        or not sku.tax_included
        or price.minimum_quantity != price.maximum_quantity
        or price.minimum_quantity != cost.quantity
        or sku.billing_unit != cost.unit
    ):
        raise ValueError("selected price is not fresh, evidenced or exactly in scope")
    scope = snapshot_scope(session, price)
    if scope != cost.expected_price_scope:
        raise ValueError("pinned price request scope differs")
    _validate_quantity(config, cost, scope)
    category = {"compute": "compute", "system_disk": "storage", "outbound": "traffic"}[
        cost.dimension
    ]
    if sku.charge_category != category:
        raise ValueError("price charge category differs from cost dimension")
    with localcontext() as calculation:
        calculation.prec = 64
        amount = price.unit_price * cost.quantity
    if amount > Decimal("9999999999999999.99999999"):
        raise ValueError("cost exceeds the database decimal range")
    if amount != amount.quantize(Decimal("0.00000001")):
        raise ValueError("cost calculation would lose decimal precision")
    assumptions = {"input_scope": scope, "evidence_sha256": cost.evidence_sha256}
    if cost.dimension == "compute":
        assumptions["compute_identity"] = _compute_identity(session, price, scope)
    return {
        "price_sku_id": sku.id,
        "price_snapshot_id": price.id,
        "evidence_id": price.evidence_id,
        "unit_price": format(price.unit_price, ".8f"),
        "amount": format(amount, ".8f"),
        "tax_status": "tax_included",
        "formula": f"{cost.quantity} {cost.unit} * {price.unit_price:.8f} CNY/{cost.unit}",
        "assumptions": assumptions,
    }


def compose_scoped_tco(
    session: Session,
    config: ScopedECSConfig,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read-only plan. Missing amounts stay NULL, including the overall total."""
    config = ScopedECSConfig.model_validate(config.model_dump())
    now = now or datetime.now(UTC)
    lines: list[dict[str, Any]] = []
    with session.no_autoflush:
        _validate_product(session, config)
        for cost in config.costs:
            line: dict[str, Any] = {
                "provider_id": config.context.provider_id,
                "product_id": config.context.product_id,
                "dimension": cost.dimension,
                "usage_quantity": str(cost.quantity),
                "usage_unit": cost.unit,
                "price_sku_id": None,
                "price_snapshot_id": None,
                "evidence_id": None,
                "unit_price": None,
                "amount": None,
                "currency": "CNY",
                "tax_status": "tax_unknown",
                "formula": None,
                "assumptions": {},
                "warning": None,
                "missing_reason": None,
            }
            if cost.treatment == "price":
                line.update(_price_line(session, config, cost, root=root, now=now))
            elif cost.treatment == "policy_zero":
                assert cost.evidence_id is not None and cost.policy_code is not None
                receipt = validate_zero_cost_policy(
                    session,
                    policy_code=cost.policy_code,
                    evidence_id=cost.evidence_id,
                    context=config.context,
                    root=root,
                    now=now,
                )
                if (
                    receipt["dimension"] != cost.dimension
                    or receipt["evidence_sha256"] != cost.evidence_sha256
                ):
                    raise ValueError("policy dimension or pinned evidence differs")
                line.update(
                    evidence_id=cost.evidence_id,
                    unit_price="0",
                    amount="0",
                    tax_status="tax_included",
                    formula="0 CNY for evidenced policy conditions; not a tariff",
                    assumptions={"policy_receipt": receipt},
                )
            elif cost.treatment == "not_applicable":
                line.update(
                    amount="0",
                    tax_status="tax_included",
                    formula="Not deployed in this bounded scenario; no price asserted",
                )
            else:
                line["missing_reason"] = cost.rationale
            line["assumptions"].update(
                {
                    "treatment": cost.treatment,
                    "rationale": cost.rationale,
                    "missing_prices_are_not_zero": True,
                    "customer_eligible": False,
                }
            )
            lines.append(line)
    missing = sum(line["amount"] is None for line in lines)
    subtotal = sum(
        (Decimal(line["amount"]) for line in lines if line["amount"] is not None), Decimal(0)
    )
    if subtotal > Decimal("9999999999999999.99999999"):
        raise ValueError("subtotal exceeds the database decimal range")
    payload = config.model_dump(mode="json")
    compute_line = next(line for line in lines if line["dimension"] == "compute")
    compute_identity = compute_line["assumptions"].get(
        "compute_identity", _unknown_compute_identity()
    )
    report: dict[str, Any] = {
        "rule_version": RULE_VERSION,
        "config": payload,
        "config_sha256": _hash(payload),
        "line_items": lines,
        "compute_identity": compute_identity,
        "known_subtotal": format(subtotal, ".8f"),
        "total": format(subtotal, ".8f") if not missing else None,
        "missing_price_count": missing,
        "completeness_status": "missing_price" if missing else "complete",
        "freshness_status": "fresh" if not missing else "unknown",
        "tax_amount": None,
        "tax_scope": "tax_included",
        "currency": "CNY",
        "comparability_status": "needs_review",
        "model_approved": False,
        "customer_eligible": False,
        "limitations": [
            "Single-provider explicit architecture only",
            "No SKU/performance/availability equivalence",
            "No currency or duration conversion",
            "Not a purchase quote or approved DecisionResult",
        ],
    }
    report["content_hash"] = _hash(report)
    return report


def _scenario_fields(config: ScopedECSConfig, report: dict[str, Any]) -> dict[str, Any]:
    duration_origin = "explicit_internal_scenario_assumption"
    if report["compute_identity"]["compute_sku_code"] is not None:
        duration_origin = (
            "exact_quoted_duration"
            if config.price_basis == "official_bounded_quote"
            else "labeled_30_day_catalog_column"
        )
    return {
        "name": config.name,
        "market_mode": "domestic",
        "billing_period": "explicit_hours",
        "target_currency": "CNY",
        "workload_profile": {
            **report["compute_identity"],
            "compute_instance_hours": str(config.context.duration_hours),
            "outbound_gb": str(config.outbound_gb),
            "disk_capacity": str(config.disk_capacity),
            "disk_capacity_unit": config.disk_capacity_unit,
            "region": config.context.region,
            "scoped_ecs_config": report["config"],
            "config_sha256": report["config_sha256"],
            "required_cost_dimensions": [cost.dimension for cost in config.costs],
        },
        "assumptions": {
            "tax_scope": "tax_included",
            "price_basis": config.price_basis,
            "customer_eligible": False,
            "model_approved": False,
            "scope": "bounded_ecs_architecture_only",
            "duration_hours": str(config.context.duration_hours),
            "duration_origin": duration_origin,
            "duration_comparison_policy": "No cross-provider duration normalization",
            "usage_origin": "explicit_internal_config_not_customer_requirements",
        },
        "status": "active",
    }


def _line_fields(line: dict[str, Any]) -> dict[str, Any]:
    return {
        key: Decimal(value)
        if key in {"usage_quantity", "unit_price", "amount"} and value is not None
        else value
        for key, value in line.items()
    }


def persist_scoped_tco(
    session: Session,
    config: ScopedECSConfig,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Coordinator-only write API; caller MUST commit or roll back the transaction.

    Preflight runs before any insert. On any persistence failure the caller must
    roll back. Existing scenario versions and runs are never mutated.
    """
    if session.new or session.dirty or session.deleted:
        raise ValueError("use a clean coordinator session for scoped TCO persistence")
    config = ScopedECSConfig.model_validate(config.model_dump())
    now = now or datetime.now(UTC)
    report = compose_scoped_tco(session, config, root=root, now=now)
    fields = _scenario_fields(config, report)
    scenario = session.scalar(
        select(PricingScenario).where(
            PricingScenario.scenario_code == config.scenario_code,
            PricingScenario.scenario_version == config.scenario_version,
        )
    )
    if scenario is not None and any(
        getattr(scenario, key) != value for key, value in fields.items()
    ):
        raise ValueError("immutable scenario version differs; create a new version")
    run_code = f"{RULE_VERSION}_{report['content_hash']}"
    run = session.scalar(select(CostCalculationRun).where(CostCalculationRun.run_code == run_code))
    if run is not None:
        if scenario is None or run.scenario_id != scenario.id or not _stored_matches(run, report):
            raise ValueError("existing immutable scoped run differs")
        return {**report, "scenario_id": scenario.id, "run_id": run.id, "created": False}
    if scenario is None:
        scenario = PricingScenario(
            scenario_code=config.scenario_code, scenario_version=config.scenario_version, **fields
        )
        session.add(scenario)
        session.flush()
    run = CostCalculationRun(
        scenario_id=scenario.id,
        run_code=run_code,
        rule_version=RULE_VERSION,
        price_snapshot_cutoff=now,
        started_at=now,
        completed_at=now,
        status="partial" if report["missing_price_count"] else "succeeded",
        currency="CNY",
        provider_count=1,
        line_item_count=len(report["line_items"]),
        warning_count=report["missing_price_count"],
        error_count=0,
        content_hash=report["content_hash"],
    )
    session.add(run)
    session.flush()
    session.add_all(
        CostLineItem(run_id=run.id, **_line_fields(line)) for line in report["line_items"]
    )
    session.add(
        TCOResult(
            run_id=run.id,
            scenario_id=scenario.id,
            provider_id=config.context.provider_id,
            product_id=config.context.product_id,
            subtotal=Decimal(report["known_subtotal"]),
            total=Decimal(report["total"]) if report["total"] is not None else None,
            tax_amount=None,
            currency="CNY",
            billing_period="explicit_hours",
            completeness_status=report["completeness_status"],
            freshness_status=report["freshness_status"],
            comparability_status="needs_review",
            warning_count=report["missing_price_count"],
            missing_price_count=report["missing_price_count"],
        )
    )
    session.flush()
    return {**report, "scenario_id": scenario.id, "run_id": run.id, "created": True}


def _stored_matches(run: CostCalculationRun, report: dict[str, Any]) -> bool:
    def utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    by_dimension = {line.dimension: line for line in run.line_items}
    if (
        len(run.line_items) != len(report["line_items"])
        or len(by_dimension) != len(run.line_items)
        or run.content_hash != report["content_hash"]
        or run.rule_version != RULE_VERSION
        or run.currency != "CNY"
        or run.provider_count != 1
        or run.line_item_count != len(report["line_items"])
        or run.warning_count != report["missing_price_count"]
        or run.error_count != 0
        or run.status != ("partial" if report["missing_price_count"] else "succeeded")
        or run.run_code != f"{RULE_VERSION}_{report['content_hash']}"
        or utc(run.price_snapshot_cutoff) != utc(run.started_at)
        or run.completed_at is None
        or utc(run.completed_at) < utc(run.started_at)
        or len(run.results) != 1
    ):
        return False
    for line in report["line_items"]:
        stored = by_dimension.get(line["dimension"])
        if stored is None or any(
            getattr(stored, key) != value for key, value in _line_fields(line).items()
        ):
            return False
        if stored.price_snapshot is not None and utc(stored.price_snapshot.captured_at) > utc(
            run.price_snapshot_cutoff
        ):
            return False
        receipt = line["assumptions"].get("policy_receipt")
        if receipt is not None and datetime.fromisoformat(receipt["captured_at"]) > utc(
            run.price_snapshot_cutoff
        ):
            return False
    result = run.results[0]
    context = report["config"]["context"]
    return bool(
        result.scenario_id == run.scenario_id
        and result.provider_id == context["provider_id"]
        and result.product_id == context["product_id"]
        and result.currency == "CNY"
        and result.billing_period == "explicit_hours"
        and result.tax_amount is None
        and result.subtotal == Decimal(report["known_subtotal"])
        and result.total == (Decimal(report["total"]) if report["total"] is not None else None)
        and result.completeness_status == report["completeness_status"]
        and result.freshness_status == report["freshness_status"]
        and result.comparability_status == "needs_review"
        and result.warning_count == result.missing_price_count == report["missing_price_count"]
    )


def scoped_tco_result_currently_complete(
    session: Session, result: TCOResult, *, root: Path | None = None, now: datetime | None = None
) -> bool:
    """Aggregate validator dispatch target; recheck evidence at every consumption."""
    with session.no_autoflush:
        return _currently_complete(session, result, root=root, now=now)


def scoped_tco_result_currently_valid(
    session: Session, result: TCOResult, *, root: Path | None = None, now: datetime | None = None
) -> bool:
    """Validate stored structure and policies without promoting partial costs to complete."""
    with session.no_autoflush:
        return _currently_complete(session, result, root=root, now=now, require_complete=False)


def _currently_complete(
    session: Session,
    result: TCOResult,
    *,
    root: Path | None,
    now: datetime | None,
    require_complete: bool = True,
) -> bool:
    try:
        if (
            result.run.rule_version != RULE_VERSION
            or (require_complete and result.completeness_status != "complete")
            or result.scenario_id != result.run.scenario_id
            or len(result.run.results) != 1
            or result.run.results[0] is not result
        ):
            return False
        now = now or datetime.now(UTC)
        started = result.run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if started > now:
            return False
        config = ScopedECSConfig.model_validate(
            result.scenario.workload_profile["scoped_ecs_config"]
        )
        if (config.scenario_code, config.scenario_version) != (
            result.scenario.scenario_code,
            result.scenario.scenario_version,
        ):
            return False
        report = compose_scoped_tco(session, config, root=root, now=now)
        if any(
            getattr(result.scenario, key) != value
            for key, value in _scenario_fields(config, report).items()
        ):
            return False
        return (
            not require_complete or report["completeness_status"] == "complete"
        ) and _stored_matches(result.run, report)
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError, AttributeError, IndexError):
        return False
