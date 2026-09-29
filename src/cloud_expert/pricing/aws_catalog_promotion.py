"""Exact AWS catalog promotion with policy evidence; no TCO or approval grants."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.pricing.aws_billing_policy import (
    canonical,
    digest,
    evidence_row,
    prepare_billing_policy,
    snapshot_binding,
    utc,
    verified_snapshot,
)
from cloud_expert.pricing.large_catalog import inspect_large_ec2_catalog
from cloud_expert.pricing.official_catalog import CatalogSelection, inspect_official_catalog

RULE = "aws_catalog_policy_backed_promotion_v1"


def decimal8(value: str) -> Decimal:
    """Numeric(24,8) is an exact boundary, never a rounding instruction."""
    number = Decimal(value)
    with localcontext() as context:
        context.prec = 64
        if (
            not number.is_finite()
            or number < 0
            or number >= Decimal(10) ** 16
            or number != number.quantize(Decimal("0.00000001"))
        ):
            raise ValueError("price/range cannot be represented exactly as Numeric(24,8)")
    return number


def _clean(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        raise ValueError("clean coordinator session required")


def _context(session: Session, product_code: str) -> dict[str, Any]:
    products = list(
        session.scalars(
            select(Product)
            .join(Provider)
            .where(
                Provider.code == "aws",
                Product.code == product_code,
                Product.market_mode == "international",
            )
        )
    )
    regions = list(
        session.scalars(
            select(Region)
            .join(Provider)
            .where(
                Provider.code == "aws",
                Region.code == "us-east-1",
            )
        )
    )
    if len(products) != 1 or len(regions) != 1:
        raise ValueError("unique AWS international product/region required")
    product, region = products[0], regions[0]
    partition = region.cloud_partition
    if (
        region.market_mode != "international"
        or region.country_code != "US"
        or not region.is_active
        or partition is None
        or partition.partition_code != "aws"
        or partition.market_mode != "international"
        or not partition.is_active
        or partition.provider_id != product.provider_id
        or region.provider_id != product.provider_id
    ):
        raise ValueError("AWS international partition/region mismatch")
    return {
        "provider_id": product.provider_id,
        "product_id": product.id,
        "region_id": region.id,
        "product_code": product_code,
        "region_code": "us-east-1",
        "market_mode": "international",
        "cloud_partition": "aws",
        "country_code": "US",
        "currency": "USD",
    }


def _units(selection: CatalogSelection, product: str) -> tuple[str, str, str, list[str]]:
    if selection.product_family == "Data Transfer":
        raise ValueError(
            "Data Transfer quarantined: zero catalog price is not free Internet egress"
        )
    if product == "ec2" and selection.product_family == "Compute Instance":
        if selection.attributes.get("operatingSystem") != "Linux":
            raise ValueError("only explicit Linux compute unit policy is supported")
        return "compute", "instance-hour", "hourly", ["tax", "compute_unit"]
    if product == "s3" and selection.product_family == "Storage":
        if (
            selection.attributes.get("volumeType") != "Standard"
            or selection.attributes.get("storageClass") != "General Purpose"
        ):
            raise ValueError("only explicit S3 Standard storage policy is supported")
        return "storage", "GiB-month", "monthly", ["tax", "storage_unit", "storage_period"]
    if product == "s3" and selection.product_family == "API Request":
        group = selection.attributes.get("group")
        if group not in {"S3-API-Tier1", "S3-API-Tier2"} or selection.attributes.get(
            "usagetype"
        ) != {
            "S3-API-Tier1": "Requests-Tier1",
            "S3-API-Tier2": "Requests-Tier2",
        }.get(group or ""):
            raise ValueError("explicit Standard request group and usage type required")
        return "request", "request", "usage", ["tax", "request_unit"]
    raise ValueError("unsupported product/family; no implicit unit policy")


def prepare_aws_catalog_promotion(
    session: Session,
    *,
    snapshot_id: int,
    policy_snapshot_id: int,
    selections: list[CatalogSelection],
    raw_root: Path,
    as_of: datetime,
    max_age_days: int = 7,
) -> dict[str, Any]:
    """Read-only deterministic plan; revalidated against raw bytes on every apply."""
    _clean(session)
    session.expire_all()
    snapshot, entry, manifest, path = verified_snapshot(
        session, snapshot_id, raw_root=raw_root, as_of=as_of, max_age_days=max_age_days
    )
    product = entry.product_code
    assert product is not None
    for selection in selections:
        _units(selection, product)
    policy = prepare_billing_policy(
        session,
        policy_snapshot_id,
        product_code=product,
        raw_root=raw_root,
        as_of=as_of,
        max_age_days=max_age_days,
    )
    if product == "ec2":
        inspected = inspect_large_ec2_catalog(
            path,
            entry=entry,
            manifest=manifest,
            selections=selections,
            as_of=as_of,
            max_age_days=max_age_days,
        )
    else:
        if snapshot.content_length_bytes > min(
            52_428_800, entry.fetch_policy.max_content_length_bytes
        ):
            raise ValueError("small catalog size limit exceeded")
        inspected = inspect_official_catalog(
            path.read_bytes(),
            entry=entry,
            manifest=manifest,
            selections=selections,
            as_of=as_of,
            max_age_days=max_age_days,
        )
    context = _context(session, product)
    binding = snapshot_binding(snapshot, entry, manifest)
    selected = {selection.sku: selection for selection in selections}
    rows = []
    config = {
        "snapshot_id": snapshot_id,
        "policy_snapshot_id": policy_snapshot_id,
        "selections": [s.model_dump() for s in sorted(selections, key=lambda s: s.sku)],
        "max_age_days": max_age_days,
    }
    for rate in inspected["records"]:
        category, unit, period, kinds = _units(selected[rate["sku"]], product)
        price = decimal8(rate["unit_price"])
        minimum = decimal8(rate["begin_range"])
        maximum = None if rate["end_range"] == "Inf" else decimal8(rate["end_range"])
        policies = [row for row in policy["records"] if row["kind"] in kinds]
        if {row["kind"] for row in policies} != set(kinds):
            raise ValueError("separate official tax/unit evidence required")
        policy_refs = [
            {
                key: row[key]
                for key in (
                    "kind",
                    "snapshot_record_id",
                    "source_document_id",
                    "raw_sha256",
                    "locator",
                    "content_hash",
                    "parser_rule",
                )
            }
            for row in policies
        ]
        payload = {
            "rule_version": RULE,
            "scope": "internal_reference_only",
            "customer_eligible": False,
            "price_basis": "public_catalog",
            "realtime": False,
            **binding,
            **context,
            "catalog_version": inspected["catalog_version"],
            "publication_date": inspected["publication_date"],
            "catalog_record": rate,
            "policy_evidence_references": policy_refs,
            "tax_status": "tax_excluded",
            "tax_included": False,
            "tax_condition": "unless_otherwise_noted",
            "tax_rate": None,
            "customer_payable_tax": "unknown",
            "billing_unit": unit,
            "billing_period": period,
            "tier_semantics": "graduated_begin_inclusive_end_exclusive",
            "requires_all_tiers": True,
            "hours_per_month": None,
            "approval_granted": False,
            "promotion_config": config,
        }
        excerpt = canonical(payload)
        rows.append(
            {
                "catalog_sku": rate["sku"],
                "rate_code": rate["rate_code"],
                "sku": {
                    "provider_id": context["provider_id"],
                    "product_id": context["product_id"],
                    "region_id": context["region_id"],
                    "sku_id": None,
                    "provider_price_code": f"aws:us-east-1:{rate['sku']}",
                    "charge_category": category,
                    "billing_mode": "on_demand",
                    "billing_unit": unit,
                    "currency": "USD",
                    "tax_included": False,
                },
                "price": {
                    "unit_price": str(price),
                    "minimum_quantity": str(minimum),
                    "maximum_quantity": None if maximum is None else str(maximum),
                    "billing_period": period,
                    "discount_type": "list",
                    "captured_at": binding["captured_at"],
                    "effective_from": utc(
                        datetime.fromisoformat(rate["effective_from"])
                    ).isoformat(),
                    "effective_to": None,
                    "source_payload_path": snapshot.storage_path,
                },
                "evidence": {
                    **binding,
                    "locator": rate["price_locator"],
                    "parser_rule": RULE,
                    "evidence_type": "json_path",
                    "excerpt": excerpt,
                    "content_hash": digest(excerpt),
                },
            }
        )
    plan = {
        "rule_version": RULE,
        "config": config,
        "catalog": binding,
        "context": context,
        "policy": policy,
        "rows": rows,
        "scope": "internal_reference_only",
        "customer_eligible": False,
        "complete_tco": False,
        "gaps": [
            "customer_payable_tax_unknown",
            "internet_egress_quarantined",
            "scenario_component_coverage_not_validated",
            "account_tier_aggregation_not_validated",
        ],
    }
    plan["plan_sha256"] = digest(canonical(plan))
    return plan


def _price_values(row: dict[str, Any]) -> dict[str, Any]:
    values = dict(row["price"])
    for key in ("unit_price", "minimum_quantity", "maximum_quantity"):
        values[key] = None if values[key] is None else decimal8(values[key])
    for key in ("captured_at", "effective_from", "effective_to"):
        values[key] = None if values[key] is None else datetime.fromisoformat(values[key])
    return values


def _same(value: Any, expected: Any) -> bool:
    if isinstance(value, datetime) and isinstance(expected, datetime):
        return utc(value) == utc(expected)
    return bool(value == expected)


def _persist(session: Session, plan: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    evidence = {}
    created_evidence = created_skus = created_prices = existing_prices = 0
    links = []
    for row in [*plan["policy"]["records"], *(r["evidence"] for r in plan["rows"])]:
        item = evidence_row(session, row)
        if item is None and apply:
            item = evidence_row(session, row, apply=True)
            created_evidence += 1
        evidence[(row["snapshot_record_id"], row["locator"], row["parser_rule"])] = item
    for row in plan["rows"]:
        skus = list(
            session.scalars(
                select(PriceSKU).where(
                    PriceSKU.provider_id == row["sku"]["provider_id"],
                    PriceSKU.provider_price_code == row["sku"]["provider_price_code"],
                )
            )
        )
        if len(skus) > 1 or any(
            any(not _same(getattr(sku, k), v) for k, v in row["sku"].items()) for sku in skus
        ):
            raise ValueError("immutable PriceSKU conflict")
        sku = skus[0] if skus else None
        if sku is None and apply:
            sku = PriceSKU(**row["sku"])
            session.add(sku)
            session.flush()
            created_skus += 1
        proof = row["evidence"]
        ev = evidence[(proof["snapshot_record_id"], proof["locator"], proof["parser_rule"])]
        prices = (
            list(session.scalars(select(PriceSnapshot).where(PriceSnapshot.evidence_id == ev.id)))
            if ev
            else []
        )
        values = _price_values(row)
        if len(prices) > 1 or any(
            sku is None
            or price.price_sku_id != sku.id
            or any(not _same(getattr(price, k), v) for k, v in values.items())
            for price in prices
        ):
            raise ValueError("immutable PriceSnapshot conflict")
        # A different evidence identity cannot masquerade as the same raw rate.
        if sku is not None:
            others = list(
                session.scalars(
                    select(PriceSnapshot)
                    .join(Evidence)
                    .where(
                        PriceSnapshot.price_sku_id == sku.id,
                        Evidence.snapshot_record_id == proof["snapshot_record_id"],
                        Evidence.locator == proof["locator"],
                    )
                )
            )
            if any(ev is None or other.evidence_id != ev.id for other in others):
                raise ValueError("competing parser price for same immutable catalog rate")
        price = prices[0] if prices else None
        if price is not None:
            existing_prices += 1
        elif apply:
            assert sku is not None and ev is not None
            price = PriceSnapshot(**values, price_sku_id=sku.id, evidence_id=ev.id)
            session.add(price)
            session.flush()
            created_prices += 1
        links.append(
            {
                "rate_code": row["rate_code"],
                "evidence_id": ev.id if ev else None,
                "price_sku_id": sku.id if sku else None,
                "price_snapshot_id": price.id if price else None,
            }
        )
    policy_ids = [
        item.id
        for row in plan["policy"]["records"]
        if (item := evidence[(row["snapshot_record_id"], row["locator"], row["parser_rule"])])
        is not None
    ]
    return {
        "evidence_created": created_evidence,
        "policy_evidence_ids": policy_ids,
        "price_skus_created": created_skus,
        "price_snapshots_created": created_prices,
        "existing_prices": existing_prices,
        "prices_planned": len(plan["rows"]),
        "links": links,
    }


def apply_aws_catalog_promotion(
    session: Session,
    plan: dict[str, Any],
    *,
    raw_root: Path,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Default dry-run. Atomic savepoint, caller-owned outer transaction/commit."""
    _clean(session)
    now = now or datetime.now(UTC)
    if plan.get("rule_version") != RULE or plan.get("plan_sha256") != digest(
        canonical({k: v for k, v in plan.items() if k != "plan_sha256"})
    ):
        raise ValueError("promotion plan hash/version mismatch")
    config = plan["config"]
    if apply:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            driver = connection.connection.driver_connection
            if not driver.in_transaction:  # type: ignore[union-attr]
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name != "postgresql":
            raise ValueError("unsupported write dialect")

    def execute() -> dict[str, Any]:
        session.expire_all()
        if apply:
            session.execute(
                select(Provider)
                .where(Provider.id == plan["context"]["provider_id"])
                .with_for_update()
            ).scalar_one()
            session.execute(
                select(SnapshotRecord)
                .where(SnapshotRecord.id.in_([config["snapshot_id"], config["policy_snapshot_id"]]))
                .order_by(SnapshotRecord.id)
                .with_for_update()
            ).all()
        current = prepare_aws_catalog_promotion(
            session,
            snapshot_id=config["snapshot_id"],
            policy_snapshot_id=config["policy_snapshot_id"],
            selections=[CatalogSelection.model_validate(s) for s in config["selections"]],
            raw_root=raw_root,
            as_of=now,
            max_age_days=config["max_age_days"],
        )
        if current != plan:
            raise ValueError("promotion inputs changed; replan required")
        preflight = _persist(session, plan, apply=False)
        if not apply:
            return preflight
        written = _persist(session, plan, apply=True)
        # SQLite Numeric storage may pass through a float; verify persisted values
        # before the coordinator can commit, not only the input Decimal scale.
        session.expire_all()
        persisted = _persist(session, plan, apply=False)
        if persisted["existing_prices"] != len(plan["rows"]) or len(
            persisted["policy_evidence_ids"]
        ) != len(plan["policy"]["records"]):
            raise ValueError("incomplete persisted price or policy set")
        return written

    if apply:
        with session.begin_nested():
            result = execute()
        session.expire_all()
    else:
        result = execute()
    return {
        **result,
        "plan_sha256": plan["plan_sha256"],
        "applied": apply,
        "transaction_committed": False,
        "customer_eligible": False,
        "approvals_granted": 0,
        "scope": "internal_reference_only",
        "complete_tco": False,
        "gaps": plan["gaps"],
    }


def aws_catalog_price_valid(
    session: Session, price: PriceSnapshot, *, raw_root: Path, now: datetime | None = None
) -> bool:
    """Consumption hook: revalidate policies, all tiers, raw hash and persisted values."""
    try:
        proof = price.evidence
        if proof.parser_rule != RULE or proof.review_status == "rejected":
            return False
        payload = json.loads(proof.excerpt)
        config = payload["promotion_config"]
        plan = prepare_aws_catalog_promotion(
            session,
            snapshot_id=config["snapshot_id"],
            policy_snapshot_id=config["policy_snapshot_id"],
            selections=[CatalogSelection.model_validate(s) for s in config["selections"]],
            raw_root=raw_root,
            as_of=now or datetime.now(UTC),
            max_age_days=config["max_age_days"],
        )
        report = _persist(session, plan, apply=False)
        return (
            len(report["policy_evidence_ids"]) == len(plan["policy"]["records"])
            and report["existing_prices"] == len(plan["rows"])
            and any(link["price_snapshot_id"] == price.id for link in report["links"])
        )
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError):
        return False
