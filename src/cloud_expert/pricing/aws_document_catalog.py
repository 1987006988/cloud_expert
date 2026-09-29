"""Versioned read-only catalog/document derivation, never price activation.

Coordinator contract:
1. Persist separately verified aws_document_policy records without relabeling
   their documentation sources. Supply DocumentPolicyReference(kind, evidence_id,
   content_hash) for general tax plus the exact request or compute claim set.
2. prepare_document_catalog_plan builds candidate sku/price/evidence dictionaries.
   validate_document_catalog_plan rebuilds everything before a coordinator write.
3. After coordinator-owned insertion/flush, use a CLEAN session to call
   validate_document_catalog_prices with every new PriceSnapshot ID in the plan.
   It reloads stored values and requires all tiers; then the separate lifecycle
   writer can bind plan_sha256, group hashes and returned row fingerprints.

No apply function, commit, activation, legacy fallback, model approval or TCO.
The parent must enforce lifecycle state/locking/atomicity separately. Each call
rechecks current registries, documents, raw files, complete OnDemand tiers and
exact stored fields. IDs/created_at are storage metadata, not vendor assertions;
all business fields and foreign-key targets are covered by the field proof map.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence
from cloud_expert.pricing.aws_billing_policy import (
    canonical,
    digest,
    snapshot_binding,
    utc,
    verified_snapshot,
)
from cloud_expert.pricing.aws_catalog_promotion import _context, decimal8
from cloud_expert.pricing.aws_document_policy import prepare_document_policy
from cloud_expert.pricing.large_catalog import inspect_large_ec2_catalog
from cloud_expert.pricing.official_catalog import (
    MAX_BYTES,
    CatalogSelection,
    decode_catalog_json,
    inspect_official_catalog,
    validate_official_catalog_source,
)

RULE = "aws_document_catalog_derivation_v2"
CATALOG_SOURCES = {
    "aws_s3_pricing_bulk_us_east_1": "s3",
    "aws_ec2_pricing_bulk_us_east_1": "ec2",
}
CLAIMS = {
    "general_tax_exclusion": ("aws_pricing_principles", "general_aws_pricing_principles_only"),
    "general_compute_units": ("aws_pricing_principles", "general_aws_pricing_principles_only"),
    "request_tier1_usage_code": ("aws_s3_billing_usage_codes", "billing_usage_codes_only"),
    "request_tier2_usage_code": ("aws_s3_billing_usage_codes", "billing_usage_codes_only"),
    "compute_running_lifecycle": (
        "aws_ec2_instance_lifecycle_billing",
        "ec2_instance_usage_lifecycle_only",
    ),
}
EVIDENCE_FIELDS = (
    "source_document_id",
    "snapshot_record_id",
    "locator",
    "parser_rule",
    "evidence_type",
    "excerpt",
    "content_hash",
)
ADMISSIBLE_EXTRACTION_STATES = {"machine_extracted", "pending_review", "human_reviewed"}


class DocumentPolicyReference(BaseModel):
    """Caller-pinned actual Evidence identity, not an unpersisted excerpt or flag."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal[
        "general_tax_exclusion",
        "general_compute_units",
        "request_tier1_usage_code",
        "request_tier2_usage_code",
        "compute_running_lifecycle",
    ]
    evidence_id: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    snapshot_id: int = Field(gt=0)
    selections: list[CatalogSelection] = Field(min_length=1, max_length=100)
    policy_references: list[DocumentPolicyReference] = Field(min_length=2, max_length=5)
    max_age_days: int = Field(ge=1, le=90)


def _fresh(session: Session, as_of: datetime) -> None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("aware validation time required")
    if session.new or session.dirty or session.deleted:
        raise ValueError("clean coordinator session required; flush explicitly before validation")
    session.expire_all()


def _contained(root: Path, relative: str) -> Path:
    parts = PureWindowsPath(relative)
    if not relative or parts.drive or parts.root or ".." in parts.parts:
        raise ValueError("catalog snapshot path must be relative and contained")
    path = (root.resolve() / parts.as_posix()).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("catalog snapshot path escapes raw root or is missing")
    return path


def _selection(selection: CatalogSelection, product: str) -> tuple[str, str, str, set[str]]:
    attrs = selection.attributes
    common = {
        "servicecode": "AmazonEC2" if product == "ec2" else "AmazonS3",
        "regionCode": "us-east-1",
        "locationType": "AWS Region",
    }
    if selection.currency != "USD" or any(attrs.get(k) != v for k, v in common.items()):
        raise ValueError("exact commercial us-east-1 USD selection required")
    if product == "ec2" and selection.product_family == "Compute Instance":
        instance = attrs.get("instanceType", "")
        required = {
            "operatingSystem": "Linux",
            "tenancy": "Shared",
            "preInstalledSw": "NA",
            "capacitystatus": "Used",
            "marketoption": "OnDemand",
            "licenseModel": "No License required",
            "operation": "RunInstances",
            "usagetype": f"BoxUsage:{instance}",
        }
        if (
            not re.fullmatch(r"[A-Za-z0-9-]+\.[A-Za-z0-9-]+", instance)
            or selection.unit != "Hrs"
            or any(attrs.get(k) != v for k, v in required.items())
        ):
            raise ValueError("exact Linux Shared Used OnDemand instance-hour scope required")
        return (
            "compute",
            "instance-hour",
            "hourly",
            {
                "general_tax_exclusion",
                "general_compute_units",
                "compute_running_lifecycle",
            },
        )
    if product == "s3" and selection.product_family == "API Request":
        group = attrs.get("group")
        tier = {"S3-API-Tier1": "1", "S3-API-Tier2": "2"}.get(group or "")
        if (
            tier is None
            or selection.unit != "Requests"
            or attrs.get("operation") != ""
            or attrs.get("usagetype") != f"Requests-Tier{tier}"
        ):
            raise ValueError("exact S3 Tier1/Tier2 request group and operation required")
        return (
            "request",
            "request",
            "usage",
            {
                "general_tax_exclusion",
                f"request_tier{tier}_usage_code",
            },
        )
    raise ValueError("storage, transfer and other catalog scopes are not supported")


def _unit_proof(rate: dict[str, Any], selection: CatalogSelection) -> dict[str, Any]:
    attrs = rate["product_attributes"]
    if any(re.search(r"tax|vat|duty", key, re.IGNORECASE) for key in attrs):
        raise ValueError("unsupported explicit catalog tax attribute; no exception inference")
    price = decimal8(rate["unit_price"])
    number = r"([0-9]{1,24}(?:\.[0-9]{1,18})?)"
    if selection.product_family == "Compute Instance":
        pattern = (
            rf"\${number} per On Demand Linux {re.escape(attrs['instanceType'])} Instance Hour"
        )
        match = re.fullmatch(pattern, rate["description"])
        if match is None or Decimal(match[1]) != price:
            raise ValueError("catalog description does not prove exact Hrs to instance-hour rate")
        denominator, amount = 1, match[1]
    else:
        tier1 = attrs["group"] == "S3-API-Tier1"
        group_description = (
            "PUT/COPY/POST or LIST requests" if tier1 else "GET and all other requests"
        )
        description = "PUT, COPY, POST, or LIST requests" if tier1 else "GET and all other requests"
        count = r"([1-9][0-9]{0,8}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,2})"
        match = re.fullmatch(
            rf"\${number} per {count} {re.escape(description)}", rate["description"]
        )
        if attrs.get("groupDescription") != group_description or match is None:
            raise ValueError("catalog request description/group does not prove denominator")
        denominator, amount = int(match[2].replace(",", "")), match[1]
        with localcontext() as context:
            context.prec = 64
            if price * denominator != Decimal(amount):
                raise ValueError(
                    "catalog per-one request price disagrees with described denominator"
                )
    return {
        "basis": "catalog_unit_and_exact_description_amount_identity",
        "catalog_unit": rate["unit"],
        "catalog_price_denominator": 1,
        "description_quantity": denominator,
        "description_amount_usd": amount,
        "identity": "pricePerUnit.USD * description_quantity == description_amount_usd",
        "unit_price_rescaled": False,
        "catalog_description": rate["description"],
        "catalog_price_locator": rate["price_locator"],
        "product_attributes_locator": rate["product_locator"] + "/attributes",
    }


def _evidence_matches(evidence: Evidence, expected: dict[str, Any]) -> bool:
    return (
        type(evidence.id) is int
        and evidence.id > 0
        and evidence.review_status in ADMISSIBLE_EXTRACTION_STATES
        and evidence.confidence == 1
        and all(getattr(evidence, key) == expected[key] for key in EVIDENCE_FIELDS)
        and digest(evidence.excerpt) == evidence.content_hash
        and evidence.source_document.id == evidence.source_document_id
    )


def _documents(
    session: Session,
    references: list[DocumentPolicyReference],
    required: set[str],
    raw_root: Path,
    as_of: datetime,
    max_age_days: int,
) -> list[dict[str, Any]]:
    if (
        {ref.kind for ref in references} != required
        or len(references) != len(required)
        or len({ref.evidence_id for ref in references}) != len(references)
    ):
        raise ValueError("exact typed document claim set required; no storage or legacy fallback")
    plans: dict[int, dict[str, Any]] = {}
    result = []
    for ref in sorted(references, key=lambda ref: ref.kind):
        proof = session.get(Evidence, ref.evidence_id)
        if (
            proof is None
            or proof.content_hash != ref.content_hash
            or proof.snapshot_record_id is None
        ):
            raise ValueError("pinned document Evidence is missing or changed")
        if proof.snapshot_record_id not in plans:
            plans[proof.snapshot_record_id] = prepare_document_policy(
                session,
                proof.snapshot_record_id,
                raw_root=raw_root,
                as_of=as_of,
                max_age_days=max_age_days,
            )
        candidates = [
            r for r in plans[proof.snapshot_record_id]["records"] if r["kind"] == ref.kind
        ]
        if len(candidates) != 1 or not _evidence_matches(proof, candidates[0]):
            raise ValueError("document Evidence differs from freshly verified DOM extraction")
        row = candidates[0]
        source_id, scope = CLAIMS[ref.kind]
        if row["source_id"] != source_id or row["scope"] != scope:
            raise ValueError("document Evidence claim source/scope mismatch")
        duplicates = list(
            session.scalars(
                select(Evidence).where(
                    Evidence.snapshot_record_id == proof.snapshot_record_id,
                    Evidence.locator == proof.locator,
                    Evidence.parser_rule == proof.parser_rule,
                )
            )
        )
        if len(duplicates) != 1 or duplicates[0].id != proof.id:
            raise ValueError("ambiguous persisted document Evidence identity")
        result.append(
            {
                **ref.model_dump(),
                "reference_type": "aws_document_policy_evidence",
                "scope": scope,
                "source_id": source_id,
                **{
                    key: row[key]
                    for key in (
                        "source_document_id",
                        "snapshot_record_id",
                        "raw_sha256",
                        "source_url",
                        "manifest_sha256",
                        "registry_sha256",
                        "locator",
                        "parser_rule",
                    )
                },
            }
        )
    return result


def _field_proofs(rate: dict[str, Any], kinds: set[str]) -> dict[str, Any]:
    pointer = rate["price_locator"]

    def catalog(suffix: str) -> dict[str, str]:
        return {"basis": "catalog_dimension", "pointer": pointer + suffix}

    result: dict[str, Any] = {
        "price.unit_price": catalog("/pricePerUnit/USD"),
        "price.minimum_quantity": catalog("/beginRange"),
        "price.maximum_quantity": {**catalog("/endRange"), "Inf_maps_to": None},
        "price.effective_from": {
            "basis": "catalog_offer",
            "pointer": pointer.split("/priceDimensions/")[0] + "/effectiveDate",
        },
        "price.effective_to": {"basis": "no_end_date_in_selected_ondemand_offer", "value": None},
        "price.captured_at": {"basis": "original_catalog_snapshot.captured_at"},
        "price.source_payload_path": {"basis": "original_catalog_snapshot.storage_path"},
        "price.discount_type": {"basis": "public_ondemand_catalog_not_customer_discount"},
        "price.billing_period": {"basis": "catalog_unit_derivation_not_reporting_granularity"},
        "sku.sku_id": {"basis": "unmapped_normalized_sku_no_guess", "value": None},
        "sku.provider_price_code": {"basis": "aws:us-east-1:<exact_catalog_sku>"},
        "sku.charge_category": {"basis": "exact_catalog_product_family"},
        "sku.billing_mode": {"basis": "catalog_OnDemand_offer"},
        "sku.billing_unit": {"basis": "catalog_unit_derivation_and_scoped_document_refs"},
        "sku.currency": {"basis": "sole_catalog_pricePerUnit_currency_USD"},
        "sku.tax_included": {
            "basis": "conditional_general_exclusive_catalog_basis_only",
            "document_kind": "general_tax_exclusion",
            "not_customer_tax": True,
        },
        "price.price_sku_id": {"basis": "coordinator_links_exact_verified_sku_fields"},
        "price.evidence_id": {"basis": "coordinator_links_exact_derived_catalog_evidence"},
    }
    for field in ("provider_id", "product_id", "region_id"):
        result[f"sku.{field}"] = {"basis": "unique_verified_aws_us_east_1_database_context"}
    result["required_document_kinds"] = sorted(kinds)
    return result


def prepare_document_catalog_plan(
    session: Session,
    *,
    snapshot_id: int,
    selections: list[CatalogSelection],
    policy_references: list[DocumentPolicyReference],
    raw_root: Path,
    as_of: datetime,
    max_age_days: int = 7,
) -> dict[str, Any]:
    """Rebuild candidate rows; no writes and no lifecycle/consumption eligibility."""
    config = _Config(
        snapshot_id=snapshot_id,
        selections=sorted(selections, key=lambda s: s.sku),
        policy_references=sorted(policy_references, key=lambda r: r.kind),
        max_age_days=max_age_days,
    )
    _fresh(session, as_of)
    with session.no_autoflush:
        candidate = session.get(SnapshotRecord, snapshot_id)
        if candidate is None or candidate.source_id not in CATALOG_SOURCES:
            raise ValueError("registered bulk catalog snapshot required; no website fallback")
        _contained(raw_root, candidate.manifest_path)
        _contained(raw_root, candidate.storage_path)
        snapshot, entry, manifest, path = verified_snapshot(
            session,
            snapshot_id,
            raw_root=raw_root,
            as_of=as_of,
            max_age_days=max_age_days,
        )
        authorization = validate_official_catalog_source(entry)
        product = CATALOG_SOURCES[candidate.source_id]
        if (
            entry.source_id != candidate.source_id
            or entry.product_code != product
            or snapshot.id != snapshot_id
            or snapshot.source_document.id != snapshot.source_document_id
            or snapshot.source_document.provider_id != snapshot.source_document.provider.id
            or not snapshot.source_document.provider.is_active
            or entry.fixture_response_path is not None
            or entry.reviewed_at is None
            or entry.reviewed_at.tzinfo is None
            or utc(entry.reviewed_at) > utc(snapshot.captured_at)
            or snapshot.content_length_bytes > entry.fetch_policy.max_content_length_bytes
        ):
            raise ValueError("bulk catalog identity/authorization mismatch")
        scopes = {s.sku: _selection(s, product) for s in config.selections}
        required = set().union(*(scope[3] for scope in scopes.values()))
        references = _documents(
            session, config.policy_references, required, raw_root, as_of, max_age_days
        )
        if product == "ec2":
            inspected = inspect_large_ec2_catalog(
                path,
                entry=entry,
                manifest=manifest,
                selections=config.selections,
                as_of=as_of,
                max_age_days=max_age_days,
            )
        else:
            if snapshot.content_length_bytes > MAX_BYTES:
                raise ValueError("S3 catalog exceeds bounded inspection size")
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            inspected = inspect_official_catalog(
                raw,
                entry=entry,
                manifest=manifest,
                selections=config.selections,
                as_of=as_of,
                max_age_days=max_age_days,
            )
        context = _context(session, product)
        if context["provider_id"] != snapshot.source_document.provider_id:
            raise ValueError("catalog provider differs from product context")
        binding = snapshot_binding(snapshot, entry, manifest)
    selected = {s.sku: s for s in config.selections}
    groups = []
    for selection in config.selections:
        records = [r for r in inspected["records"] if r["sku"] == selection.sku]
        group = {
            "catalog_sku": selection.sku,
            "rate_codes": [r["rate_code"] for r in records],
            "complete_ondemand_records_sha256": digest(canonical(records)),
            "requires_all_tiers": True,
        }
        group["group_sha256"] = digest(canonical({**group, "catalog": binding}))
        groups.append(group)
    rows = []
    for rate in inspected["records"]:
        category, unit, period, kinds = scopes[rate["sku"]]
        unit_proof = _unit_proof(rate, selected[rate["sku"]])
        sku = {
            **{key: context[key] for key in ("provider_id", "product_id", "region_id")},
            "sku_id": None,
            "provider_price_code": f"aws:us-east-1:{rate['sku']}",
            "charge_category": category,
            "billing_mode": "on_demand",
            "billing_unit": unit,
            "currency": "USD",
            "tax_included": False,
        }
        price = {
            "unit_price": str(decimal8(rate["unit_price"])),
            "minimum_quantity": str(decimal8(rate["begin_range"])),
            "maximum_quantity": None
            if rate["end_range"] == "Inf"
            else str(decimal8(rate["end_range"])),
            "billing_period": period,
            "discount_type": "list",
            "captured_at": binding["captured_at"],
            "effective_from": utc(datetime.fromisoformat(rate["effective_from"])).isoformat(),
            "effective_to": None,
            "source_payload_path": binding["storage_path"],
        }
        payload = {
            "rule_version": RULE,
            **binding,
            **context,
            "scope": "internal_reference_only",
            "derivation_config": config.model_dump(mode="json"),
            "catalog_record": rate,
            "catalog_version": inspected["catalog_version"],
            "publication_date": inspected["publication_date"],
            "catalog_disclaimer": inspected["disclaimer"],
            "source_authorization": authorization,
            "policy_evidence_references": [r for r in references if r["kind"] in kinds],
            "unit_derivation": unit_proof,
            "field_proofs": _field_proofs(rate, kinds),
            "expected_sku_fields": sku,
            "expected_price_fields": price,
            "tier_group": next(g for g in groups if g["catalog_sku"] == rate["sku"]),
            "tax_status": "general_conditional_exclusive",
            "tax_condition": "except_as_otherwise_noted",
            "tax_included": False,
            "tax_rate": None,
            "customer_payable_tax": "unknown",
            "sku_tax_exception_status": "not_determined",
            "customer_eligible": False,
            "price_approval": False,
            "complete_tco": False,
            "lifecycle_activation_granted": False,
            "hours_per_month": None,
            "price_basis": "public_catalog",
            "realtime": False,
            "limitations": [
                "general_tax_basis_not_customer_tax_or_exemption",
                "document_claims_keep_original_scope_and_license",
                "no_storage_or_transfer_derivation",
                "no_account_tier_aggregation_inference",
                "no_scenario_cost_or_lifecycle_activation",
            ],
        }
        excerpt = canonical(payload)
        rows.append(
            {
                "catalog_sku": rate["sku"],
                "rate_code": rate["rate_code"],
                "sku": sku,
                "price": price,
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
        "config": config.model_dump(mode="json"),
        "catalog": binding,
        "context": context,
        "policy_evidence_references": references,
        "tier_groups": groups,
        "rows": rows,
        "scope": "internal_reference_only",
        "review_required": True,
        "customer_eligible": False,
        "price_approval": False,
        "complete_tco": False,
        "lifecycle_activation_granted": False,
        "database_write_performed": False,
    }
    plan["plan_sha256"] = digest(canonical(plan))
    return plan


def validate_document_catalog_plan(
    session: Session,
    plan: dict[str, Any],
    *,
    raw_root: Path,
    as_of: datetime,
) -> dict[str, Any]:
    """Raise on any difference, including a self-consistently rehashed forged plan."""
    if plan.get("rule_version") != RULE or plan.get("plan_sha256") != digest(
        canonical({k: v for k, v in plan.items() if k != "plan_sha256"})
    ):
        raise ValueError("document catalog plan version/hash mismatch")
    config = _Config.model_validate(plan.get("config"))
    current = prepare_document_catalog_plan(
        session,
        **config.model_dump(exclude={"selections", "policy_references"}),
        selections=config.selections,
        policy_references=config.policy_references,
        raw_root=raw_root,
        as_of=as_of,
    )
    if canonical(current) != canonical(plan):
        raise ValueError("document catalog inputs/fields changed; replan required")
    return current


def _stored_value(actual: Any, expected: Any, key: str) -> bool:
    if expected is None:
        return actual is None
    if key in {"unit_price", "minimum_quantity", "maximum_quantity"}:
        return isinstance(actual, Decimal) and actual.is_finite() and actual == decimal8(expected)
    if key in {"captured_at", "effective_from", "effective_to"}:
        return isinstance(actual, datetime) and utc(actual) == utc(datetime.fromisoformat(expected))
    return type(actual) is type(expected) and bool(actual == expected)


def validate_document_catalog_prices(
    session: Session,
    plan: dict[str, Any],
    *,
    price_snapshot_ids: list[int],
    raw_root: Path,
    as_of: datetime,
) -> dict[str, Any]:
    """Verify explicit complete successor rows, not supersession or permission to use them."""
    current = validate_document_catalog_plan(session, plan, raw_root=raw_root, as_of=as_of)
    return _validate_persisted(session, current, price_snapshot_ids)


def _validate_persisted(
    session: Session,
    current: dict[str, Any],
    price_snapshot_ids: list[int],
) -> dict[str, Any]:
    if (
        len(price_snapshot_ids) != len(current["rows"])
        or len(set(price_snapshot_ids)) != len(price_snapshot_ids)
        or any(type(value) is not int or value <= 0 for value in price_snapshot_ids)
    ):
        raise ValueError("complete unique persisted tier set required")
    remaining = {row["evidence"]["content_hash"]: row for row in current["rows"]}
    links = []
    with session.no_autoflush:
        for price_id in sorted(price_snapshot_ids):
            price = session.get(PriceSnapshot, price_id)
            if price is None or price.evidence is None or price.price_sku is None:
                raise ValueError("persisted price or foreign-key evidence is missing")
            row = remaining.pop(price.evidence.content_hash, None)
            if row is None or not _evidence_matches(price.evidence, row["evidence"]):
                raise ValueError("persisted derived pricing Evidence mismatch or duplicate tier")
            if (
                price.evidence_id != price.evidence.id
                or price.price_sku_id != price.price_sku.id
                or any(not _stored_value(getattr(price, k), v, k) for k, v in row["price"].items())
                or any(
                    not _stored_value(getattr(price.price_sku, k), v, k)
                    for k, v in row["sku"].items()
                )
            ):
                raise ValueError(
                    "persisted PriceSnapshot/PriceSKU fields differ from catalog proof"
                )
            duplicates = list(
                session.scalars(
                    select(PriceSnapshot.id)
                    .join(Evidence)
                    .where(
                        Evidence.parser_rule == RULE,
                        Evidence.snapshot_record_id == row["evidence"]["snapshot_record_id"],
                        Evidence.locator == row["evidence"]["locator"],
                        Evidence.content_hash == row["evidence"]["content_hash"],
                    )
                )
            )
            if duplicates != [price_id]:
                raise ValueError("ambiguous persisted derived price identity")
            link = {
                "price_snapshot_id": price.id,
                "price_sku_id": price.price_sku_id,
                "evidence_id": price.evidence_id,
                "evidence_content_hash": price.evidence.content_hash,
                "catalog_sku": row["catalog_sku"],
                "rate_code": row["rate_code"],
            }
            link["row_sha256"] = digest(
                canonical({**link, "sku": row["sku"], "price": row["price"]})
            )
            links.append(link)
    if remaining:
        raise ValueError("partial persisted tier set")
    return {
        "rule_version": RULE,
        "status": "persisted_candidate_fields_verified",
        "plan_sha256": current["plan_sha256"],
        "tier_groups": current["tier_groups"],
        "links": links,
        "customer_eligible": False,
        "price_approval": False,
        "complete_tco": False,
        "lifecycle_activation_granted": False,
        "database_write_performed": False,
    }


def aws_document_catalog_price_valid(
    session: Session,
    price: PriceSnapshot,
    *,
    raw_root: Path,
    now: datetime | None = None,
) -> bool:
    """Evidence-only dispatch hook; lifecycle eligibility must be checked separately.

    Only this RULE is accepted. All rows encoded by its exact derivation config
    must still exist. A revoked or missing successor never falls back to v1.
    """
    try:
        as_of = now or datetime.now(UTC)
        price_id = price.id
        _fresh(session, as_of)
        with session.no_autoflush:
            stored = session.get(PriceSnapshot, price_id)
            if stored is None or stored.evidence.parser_rule != RULE:
                return False
            payload = decode_catalog_json(stored.evidence.excerpt.encode(), limit=8 * 1024 * 1024)
            config = _Config.model_validate(payload["derivation_config"])
            plan = prepare_document_catalog_plan(
                session,
                **config.model_dump(exclude={"selections", "policy_references"}),
                selections=config.selections,
                policy_references=config.policy_references,
                raw_root=raw_root,
                as_of=as_of,
            )
            hashes = [row["evidence"]["content_hash"] for row in plan["rows"]]
            ids = list(
                session.scalars(
                    select(PriceSnapshot.id)
                    .join(Evidence)
                    .where(
                        Evidence.parser_rule == RULE,
                        Evidence.content_hash.in_(hashes),
                    )
                )
            )
        if price_id not in ids:
            return False
        _validate_persisted(session, plan, ids)
        return True
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError, AttributeError):
        return False
