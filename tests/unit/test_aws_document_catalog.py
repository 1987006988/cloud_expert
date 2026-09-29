"""Offline synthetic SQLite/HTML/catalog fixtures; never a business DB or real approval."""

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product, ProductCategory
from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import aws_billing_policy as billing
from cloud_expert.pricing import aws_document_catalog as adapter
from cloud_expert.pricing import aws_document_policy as documents
from cloud_expert.pricing.official_catalog import CatalogSelection
from tests.unit.test_aws_document_policy import LIFECYCLE, METRICS, PRINCIPLES, SOURCES, USAGE, html
from tests.unit.test_official_catalog import NOW, SKU, TERM
from tests.unit.test_official_catalog import fixture as catalog_fixture

CAPTURED = NOW - timedelta(hours=1)


@dataclass
class Data:
    session: Session
    root: Path
    snapshot: SnapshotRecord
    selection: CatalogSelection
    entries: dict[str, SourceRegistryEntry]
    references: list[adapter.DocumentPolicyReference]
    payload: dict[str, Any]
    document_snapshots: dict[str, int]

    def plan(self) -> dict[str, Any]:
        return adapter.prepare_document_catalog_plan(
            self.session,
            snapshot_id=self.snapshot.id,
            selections=[self.selection],
            policy_references=self.references,
            raw_root=self.root,
            as_of=NOW,
        )

    def rewrite_catalog(self) -> None:
        raw = billing.canonical(self.payload).encode()
        row = self.snapshot
        path = self.root / row.storage_path
        path.write_bytes(raw)
        row.content_hash = row.source_document.content_hash = billing.digest(raw)
        row.content_length_bytes = len(raw)
        manifest_path = self.root / row.manifest_path
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(content_sha256=row.content_hash, content_length_bytes=len(raw))
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.session.commit()


def store(
    session: Session, root: Path, entry: SourceRegistryEntry, raw: bytes, owner: Provider
) -> SnapshotRecord:
    stored = SnapshotStore(root).store(
        entry=entry,
        requested_url=entry.url,
        final_url=entry.url,
        http_status=200,
        content_type=entry.expected_content_type[0],
        content=raw,
        response_headers={},
        content_metadata={"synthetic": True},
        fetch_duration_ms=0,
        captured_at=CAPTURED,
    )
    manifest = stored.manifest
    doc = SourceDocument(
        provider_id=owner.id,
        source_type=entry.source_type,
        title="SYNTHETIC ONLY",
        url=entry.url,
        cloud_partition="aws",
        authority_level="official_primary",
        captured_at=CAPTURED,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        mime_type=manifest.content_type,
        http_status=200,
        is_current=True,
    )
    session.add(doc)
    session.flush()
    row = SnapshotRecord(
        source_document_id=doc.id,
        source_id=entry.source_id,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        manifest_path=str(stored.manifest_path.relative_to(root)),
        content_type=manifest.content_type,
        content_length_bytes=len(raw),
        captured_at=CAPTURED,
        change_status="first_seen",
        is_current=True,
    )
    session.add(row)
    session.flush()
    return row


def seed(
    session: Session,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    product: str = "s3",
    tier: int = 1,
) -> Data:
    owner = Provider(
        code="aws", name="Synthetic only", display_name="Synthetic only", is_active=True
    )
    category = ProductCategory(code="synthetic", name="Synthetic only")
    session.add_all([owner, category])
    session.flush()
    partition = CloudPartition(
        provider_id=owner.id,
        partition_code="aws",
        partition_name="Synthetic",
        market_mode="international",
        is_active=True,
    )
    item = Product(
        provider_id=owner.id,
        category_id=category.id,
        code=product,
        market_mode="international",
        official_name="Synthetic",
        display_name="Synthetic",
    )
    session.add_all([partition, item])
    session.flush()
    session.add(
        Region(
            provider_id=owner.id,
            code="us-east-1",
            name="Synthetic",
            country_code="US",
            market_mode="international",
            is_active=True,
            cloud_partition_id=partition.id,
        )
    )
    entry, payload, selection = catalog_fixture("AmazonS3" if product == "s3" else "AmazonEC2")
    entry = entry.model_copy(
        update={
            "source_id": f"aws_{product}_pricing_bulk_us_east_1",
            "reviewed_at": NOW - timedelta(days=2),
            "robots_checked_at": NOW - timedelta(days=2),
        }
    )
    if product == "s3":
        attrs = {
            "servicecode": "AmazonS3",
            "regionCode": "us-east-1",
            "locationType": "AWS Region",
            "operation": "",
            "usagetype": f"Requests-Tier{tier}",
            "group": f"S3-API-Tier{tier}",
            "groupDescription": "PUT/COPY/POST or LIST requests"
            if tier == 1
            else "GET and all other requests",
        }
        selection = CatalogSelection(
            sku=SKU, product_family="API Request", attributes=attrs, unit="Requests"
        )
    else:
        attrs = {
            **selection.attributes,
            "marketoption": "OnDemand",
            "usagetype": "BoxUsage:synthetic.xlarge",
        }
        selection = selection.model_copy(update={"attributes": attrs})
    payload["products"][SKU].update(productFamily=selection.product_family, attributes=attrs)
    dimensions = payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"]
    for index, row in enumerate(dimensions.values()):
        row["unit"] = selection.unit
        price = (
            ("0.0000050000" if index == 0 else "0.0000040000")
            if product == "s3"
            else "0.1920000000"
        )
        row["pricePerUnit"]["USD"] = price
        if product == "s3":
            count = 1000 if tier == 1 else 10000
            actions = (
                "PUT, COPY, POST, or LIST requests" if tier == 1 else "GET and all other requests"
            )
            row["description"] = f"${Decimal(price) * count} per {count:,} {actions}"
        else:
            row["description"] = "$0.192 per On Demand Linux synthetic.xlarge Instance Hour"
    entries = {entry.source_id: entry}
    snapshot = store(session, root, entry, billing.canonical(payload).encode(), owner)
    doc_ids = {}
    for source_id in (PRINCIPLES, USAGE if product == "s3" else LIFECYCLE):
        product_code, url, _, _ = SOURCES[source_id]
        doc_entry = SourceRegistryEntry.model_validate(
            {
                "source_id": source_id,
                "provider_code": "aws",
                "product_code": product_code,
                "market_mode": "international",
                "cloud_partition": "aws",
                "source_type": "documentation",
                "title": "SYNTHETIC ONLY",
                "url": url,
                "authority_level": "official_primary",
                "expected_content_type": ["text/html"],
                "domain_policy": {
                    "allowed_domains": ["docs.aws.amazon.com"],
                    "allow_redirects": False,
                },
                "terms_review_status": "approved",
                "automated_fetch_allowed": True,
                "reviewed_at": NOW - timedelta(days=2),
                "robots_checked_at": NOW - timedelta(days=2),
                "robots_allowed": True,
                "compliance_notes": "SYNTHETIC docs.aws.amazon.com CC-BY-SA-4.0",
            }
        )
        entries[source_id] = doc_entry
        doc_ids[source_id] = store(session, root, doc_entry, html(source_id).encode(), owner).id
    monkeypatch.setattr(billing, "get_entry_by_source_id", entries.get)
    monkeypatch.setattr(documents, "get_entry_by_source_id", entries.get)
    session.commit()
    required = (
        {"general_tax_exclusion", f"request_tier{tier}_usage_code"}
        if product == "s3"
        else {
            "general_tax_exclusion",
            "general_compute_units",
            "compute_running_lifecycle",
        }
    )
    references = []
    for snapshot_id in doc_ids.values():
        doc_plan = documents.prepare_document_policy(
            session, snapshot_id, raw_root=root, as_of=NOW, max_age_days=7
        )
        for record in doc_plan["records"]:
            proof = billing.evidence_row(session, record, apply=True)
            assert proof is not None and proof.content_hash is not None
            if record["kind"] in required:
                references.append(
                    adapter.DocumentPolicyReference(
                        kind=record["kind"],
                        evidence_id=proof.id,
                        content_hash=proof.content_hash,
                    )
                )
    session.commit()
    return Data(session, root, snapshot, selection, entries, references, payload, doc_ids)


@pytest.fixture
def data(session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Data:
    return seed(session, tmp_path, monkeypatch)


def persist_synthetic(data: Data, plan: dict[str, Any]) -> list[int]:
    """Simulate the parent's writer only in the test's isolated in-memory database."""
    skus: dict[str, PriceSKU] = {}
    ids = []
    for row in plan["rows"]:
        if row["catalog_sku"] not in skus:
            sku = PriceSKU(**row["sku"])
            data.session.add(sku)
            data.session.flush()
            skus[row["catalog_sku"]] = sku
        proof = Evidence(
            **{k: row["evidence"][k] for k in adapter.EVIDENCE_FIELDS},
            confidence=1,
            review_status="machine_extracted",
        )
        data.session.add(proof)
        data.session.flush()
        values = row["price"].copy()
        for field in ("unit_price", "minimum_quantity", "maximum_quantity"):
            values[field] = None if values[field] is None else Decimal(values[field])
        for field in ("captured_at", "effective_from", "effective_to"):
            values[field] = None if values[field] is None else datetime.fromisoformat(values[field])
        price = PriceSnapshot(
            **values, price_sku_id=skus[row["catalog_sku"]].id, evidence_id=proof.id, created_at=NOW
        )
        data.session.add(price)
        data.session.flush()
        ids.append(price.id)
    data.session.commit()
    return ids


def rehash(plan: dict[str, Any]) -> None:
    plan["plan_sha256"] = billing.digest(
        billing.canonical({k: v for k, v in plan.items() if k != "plan_sha256"})
    )


@pytest.mark.parametrize("product,tier", [("s3", 1), ("s3", 2), ("ec2", 1)])
def test_exact_complete_plan_and_persisted_fields(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    product: str,
    tier: int,
) -> None:
    data = seed(session, tmp_path, monkeypatch, product=product, tier=tier)
    plan = data.plan()
    assert plan == data.plan()
    assert plan["rule_version"] == "aws_document_catalog_derivation_v2"
    assert plan["scope"] == "internal_reference_only" and plan["review_required"]
    assert not any(
        plan[k]
        for k in (
            "customer_eligible",
            "price_approval",
            "complete_tco",
            "lifecycle_activation_granted",
            "database_write_performed",
        )
    )
    assert len(plan["rows"]) == 2 and len(plan["tier_groups"]) == 1
    assert (
        plan["rows"][0]["price"]["maximum_quantity"]
        == plan["rows"][1]["price"]["minimum_quantity"]
        == "100"
    )
    for row in plan["rows"]:
        proof = json.loads(row["evidence"]["excerpt"])
        assert row["evidence"]["source_document_id"] == data.snapshot.source_document_id
        assert data.snapshot.source_document.source_type == "pricing"
        assert proof["tax_status"] == "general_conditional_exclusive"
        assert proof["tax_rate"] is None and proof["customer_payable_tax"] == "unknown"
        assert proof["sku_tax_exception_status"] == "not_determined"
        assert proof["unit_derivation"]["catalog_price_denominator"] == 1
        assert proof["unit_derivation"]["unit_price_rescaled"] is False
        assert proof["hours_per_month"] is None
        assert proof["expected_price_fields"] == row["price"]
        assert proof["expected_sku_fields"] == row["sku"]
        for field in row["sku"]:
            assert f"sku.{field}" in proof["field_proofs"]
        for field in row["price"]:
            assert f"price.{field}" in proof["field_proofs"]
        for ref in proof["policy_evidence_references"]:
            doc_ev = session.get(Evidence, ref["evidence_id"])
            assert doc_ev is not None and doc_ev.content_hash == ref["content_hash"]
            assert doc_ev.source_document.source_type == "documentation"
            assert doc_ev.review_status == "machine_extracted"
            assert ref["reference_type"] == "aws_document_policy_evidence"
    ids = persist_synthetic(data, plan)
    report = adapter.validate_document_catalog_prices(
        session, plan, price_snapshot_ids=ids, raw_root=tmp_path, as_of=NOW
    )
    assert report["status"] == "persisted_candidate_fields_verified" and len(report["links"]) == 2
    assert all(link["row_sha256"] for link in report["links"])
    price = session.get(PriceSnapshot, ids[0])
    assert price is not None
    assert adapter.aws_document_catalog_price_valid(session, price, raw_root=tmp_path, now=NOW)


def test_no_write_statements_or_old_website_policy_called(
    data: Data, monkeypatch: pytest.MonkeyPatch
) -> None:
    statements = []
    engine = data.session.get_bind()

    def observe(_: Any, __: Any, statement: str, *args: Any) -> None:
        statements.append(statement.lstrip().split()[0].upper())

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("legacy website policy must not be called")

    monkeypatch.setattr(billing, "prepare_billing_policy", forbidden)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        plan = data.plan()
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert statements and set(statements) == {"SELECT"}
    assert data.session.scalar(select(func.count()).select_from(PriceSnapshot)) == 0


@pytest.mark.parametrize(
    "change",
    [
        "price_1000x",
        "price_divide_1000",
        "description_1",
        "description_10000",
        "description_tax",
        "description_missing",
        "wrong_actions",
        "wrong_unit",
        "wrong_group_description",
    ],
)
def test_request_denominator_and_scope_are_proved_from_catalog(data: Data, change: str) -> None:
    rate = data.payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"][f"{TERM}.TEST0"]
    if change == "price_1000x":
        rate["pricePerUnit"]["USD"] = "0.005"
    elif change == "price_divide_1000":
        rate["pricePerUnit"]["USD"] = "0.000000005"
    elif change == "description_1":
        rate["description"] = rate["description"].replace("1,000", "1")
    elif change == "description_10000":
        rate["description"] = rate["description"].replace("1,000", "10,000")
    elif change == "description_tax":
        rate["description"] += " including tax"
    elif change == "description_missing":
        rate["description"] = "Synthetic unspecified request rate"
    elif change == "wrong_actions":
        rate["description"] = "$0.005 per 1,000 GET and all other requests"
    elif change == "wrong_unit":
        rate["unit"] = "1000 Requests"
    else:
        data.payload["products"][SKU]["attributes"]["groupDescription"] = (
            "All S3 request categories"
        )
    data.rewrite_catalog()
    with pytest.raises(ValueError):
        data.plan()


@pytest.mark.parametrize(
    "field,value",
    [
        ("operatingSystem", "Windows"),
        ("tenancy", "Dedicated"),
        ("capacitystatus", "UnusedCapacityReservation"),
        ("preInstalledSw", "SQL Std"),
        ("licenseModel", "Bring your own license"),
        ("marketoption", "Reserved"),
        ("operation", "RunInstances:0002"),
        ("usagetype", "BoxUsage:other.large"),
        ("regionCode", "us-west-2"),
    ],
)
def test_compute_exact_attributes_not_linux_label_alone(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    data = seed(session, tmp_path, monkeypatch, product="ec2")
    attrs = {**data.selection.attributes, field: value}
    data.selection = data.selection.model_copy(update={"attributes": attrs})
    data.payload["products"][SKU]["attributes"] = attrs
    data.rewrite_catalog()
    with pytest.raises(ValueError):
        data.plan()


@pytest.mark.parametrize(
    "description",
    [
        "$0.192 per On Demand Windows synthetic.xlarge Instance Hour",
        "$0.192 per vCPU Hour",
        "$0.192 per On Demand Linux other.large Instance Hour",
        "$0.193 per On Demand Linux synthetic.xlarge Instance Hour",
    ],
)
def test_compute_description_must_prove_instance_hour(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    description: str,
) -> None:
    data = seed(session, tmp_path, monkeypatch, product="ec2")
    data.payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"][f"{TERM}.TEST0"][
        "description"
    ] = description
    data.rewrite_catalog()
    with pytest.raises(ValueError):
        data.plan()


@pytest.mark.parametrize("target", ["Storage", "Data Transfer", "Unknown"])
def test_no_storage_or_transfer_inference_even_with_metrics(data: Data, target: str) -> None:
    data.selection = data.selection.model_copy(update={"product_family": target, "unit": "GB-Mo"})
    with pytest.raises(ValueError, match="not supported"):
        data.plan()
    with pytest.raises(ValueError):
        adapter.DocumentPolicyReference.model_validate(
            {"kind": "storage_metric_binary_gb", "evidence_id": 106, "content_hash": "a" * 64}
        )
    assert METRICS not in {entry.source_id for entry in data.entries.values()}


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "hash",
        "wrong_kind",
        "extra",
        "duplicate",
        "legacy",
        "content",
        "rejected",
        "unknown",
        "source_type",
        "duplicate_evidence",
    ],
)
def test_document_references_are_actual_unique_scoped_evidence(data: Data, mutation: str) -> None:
    ref = data.references[0]
    ev = data.session.get(Evidence, ref.evidence_id)
    assert ev is not None
    if mutation == "missing":
        data.references[0] = ref.model_copy(update={"evidence_id": 999999})
    elif mutation == "hash":
        data.references[0] = ref.model_copy(update={"content_hash": "f" * 64})
    elif mutation == "wrong_kind":
        data.references[0] = ref.model_copy(update={"kind": "general_compute_units"})
    elif mutation == "extra":
        data.references.append(
            adapter.DocumentPolicyReference(
                kind="compute_running_lifecycle", evidence_id=9999, content_hash="f" * 64
            )
        )
    elif mutation == "duplicate":
        data.references[1] = ref
    elif mutation == "legacy":
        ev.parser_rule = billing.RULE
    elif mutation == "content":
        ev.excerpt = ev.excerpt.replace("unknown", "zero")
        ev.content_hash = billing.digest(ev.excerpt)
        data.references[0] = ref.model_copy(update={"content_hash": ev.content_hash})
    elif mutation in {"rejected", "unknown"}:
        ev.review_status = mutation
    elif mutation == "source_type":
        ev.source_document.source_type = "pricing"
    else:
        data.session.add(
            Evidence(
                **{k: getattr(ev, k) for k in adapter.EVIDENCE_FIELDS},
                confidence=1,
                review_status="machine_extracted",
            )
        )
    data.session.commit()
    with pytest.raises(ValueError):
        data.plan()


@pytest.mark.parametrize("source", ["catalog", "documents"])
@pytest.mark.parametrize("mutation", ["license", "raw", "manifest", "not_current", "url", "path"])
def test_revalidates_sources_each_time(data: Data, source: str, mutation: str) -> None:
    plan = data.plan()
    snapshot = (
        data.snapshot
        if source == "catalog"
        else data.session.get(SnapshotRecord, data.document_snapshots[PRINCIPLES])
    )
    assert snapshot is not None
    if mutation == "license":
        data.entries[snapshot.source_id] = data.entries[snapshot.source_id].model_copy(
            update={"terms_review_status": "disallowed"}
        )
    elif mutation == "raw":
        path = data.root / snapshot.storage_path
        raw = path.read_bytes()
        path.write_bytes(b"X" + raw[1:])
    elif mutation == "manifest":
        (data.root / snapshot.manifest_path).write_text("{}", encoding="utf-8")
    elif mutation == "not_current":
        snapshot.is_current = False
    elif mutation == "url":
        snapshot.source_document.url = "https://aws.amazon.com/s3/pricing/"
    else:
        snapshot.manifest_path = "../outside.json"
    data.session.commit()
    with pytest.raises(ValueError):
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_price", "0.005"),
        ("minimum_quantity", "1"),
        ("maximum_quantity", None),
        ("billing_period", "hourly"),
        ("discount_type", "unknown"),
        ("captured_at", NOW.isoformat()),
        ("effective_from", NOW.isoformat()),
        ("effective_to", NOW.isoformat()),
        ("source_payload_path", "other.json"),
    ],
)
def test_every_planned_price_field_is_rebuilt_not_just_hash_checked(
    data: Data, field: str, value: Any
) -> None:
    plan = data.plan()
    plan["rows"][0]["price"][field] = value
    rehash(plan)
    with pytest.raises(ValueError, match="changed"):
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_price", Decimal("0.005")),
        ("minimum_quantity", Decimal("1")),
        ("maximum_quantity", None),
        ("billing_period", "hourly"),
        ("discount_type", "unknown"),
        ("captured_at", NOW),
        ("effective_from", NOW),
        ("effective_to", NOW),
        ("source_payload_path", "other.json"),
    ],
)
def test_every_persisted_price_field_is_rechecked(data: Data, field: str, value: Any) -> None:
    plan = data.plan()
    ids = persist_synthetic(data, plan)
    price = data.session.get(PriceSnapshot, ids[0])
    assert price is not None
    setattr(price, field, value)
    data.session.commit()
    with pytest.raises(ValueError, match="fields"):
        adapter.validate_document_catalog_prices(
            data.session, plan, price_snapshot_ids=ids, raw_root=data.root, as_of=NOW
        )
    assert not adapter.aws_document_catalog_price_valid(
        data.session, price, raw_root=data.root, now=NOW
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", 999),
        ("product_id", 999),
        ("region_id", 999),
        ("sku_id", 999),
        ("provider_price_code", "wrong"),
        ("charge_category", "storage"),
        ("billing_mode", "reserved"),
        ("billing_unit", "1000-requests"),
        ("currency", "CNY"),
        ("tax_included", True),
    ],
)
def test_all_sku_fields_proven_in_plan(data: Data, field: str, value: Any) -> None:
    plan = data.plan()
    plan["rows"][0]["sku"][field] = value
    rehash(plan)
    with pytest.raises(ValueError):
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("billing_unit", "1000-requests"),
        ("currency", "CNY"),
        ("tax_included", True),
        ("charge_category", "storage"),
        ("provider_price_code", "changed"),
    ],
)
def test_persisted_sku_interpretation_cannot_drift(data: Data, field: str, value: Any) -> None:
    plan = data.plan()
    ids = persist_synthetic(data, plan)
    price = data.session.get(PriceSnapshot, ids[0])
    assert price is not None
    setattr(price.price_sku, field, value)
    data.session.commit()
    with pytest.raises(ValueError, match="fields"):
        adapter.validate_document_catalog_prices(
            data.session, plan, price_snapshot_ids=ids, raw_root=data.root, as_of=NOW
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_ids",
        "missing_price",
        "duplicate_ids",
        "duplicate_price",
        "rejected_price_evidence",
        "v1_rule",
        "forged_tax_zero",
        "raw",
    ],
)
def test_persisted_full_tiers_no_legacy_fallback(data: Data, mutation: str) -> None:
    plan = data.plan()
    ids = persist_synthetic(data, plan)
    first, second = [data.session.get(PriceSnapshot, value) for value in ids]
    assert first is not None and second is not None
    if mutation == "partial_ids":
        ids = ids[:1]
    elif mutation == "missing_price":
        data.session.delete(second)
    elif mutation == "duplicate_ids":
        ids = [ids[0], ids[0]]
    elif mutation == "duplicate_price":
        data.session.add(
            PriceSnapshot(
                **{k: getattr(first, k) for k in plan["rows"][0]["price"]},
                price_sku_id=first.price_sku_id,
                evidence_id=first.evidence_id,
            )
        )
    elif mutation == "rejected_price_evidence":
        first.evidence.review_status = "rejected"
    elif mutation == "v1_rule":
        first.evidence.parser_rule = "aws_catalog_policy_backed_promotion_v1"
    elif mutation == "forged_tax_zero":
        payload = json.loads(first.evidence.excerpt)
        payload["tax_rate"] = 0
        payload["customer_payable_tax"] = "zero"
        first.evidence.excerpt = billing.canonical(payload)
        first.evidence.content_hash = billing.digest(first.evidence.excerpt)
    else:
        path = data.root / data.snapshot.storage_path
        path.write_bytes(b"X" * path.stat().st_size)
    data.session.commit()
    with pytest.raises(ValueError):
        adapter.validate_document_catalog_prices(
            data.session, plan, price_snapshot_ids=ids, raw_root=data.root, as_of=NOW
        )
    if mutation not in {"partial_ids", "duplicate_ids"}:
        assert not adapter.aws_document_catalog_price_valid(
            data.session, first, raw_root=data.root, now=NOW
        )


def test_expiry_and_dirty_session_fail_closed(data: Data) -> None:
    plan = data.plan()
    with pytest.raises(ValueError):
        adapter.validate_document_catalog_plan(
            data.session, plan, raw_root=data.root, as_of=NOW + timedelta(days=8)
        )
    data.snapshot.source_document.title = "uncommitted"
    with pytest.raises(ValueError, match="clean"):
        data.plan()


@pytest.mark.parametrize(
    "mutation", ["missing_tier", "gap", "overlap", "ambiguous_offer", "currency", "tax_attribute"]
)
def test_catalog_tiers_and_conditions_fail_closed(data: Data, mutation: str) -> None:
    offers = data.payload["terms"]["OnDemand"][SKU]
    dimensions = offers[TERM]["priceDimensions"]
    if mutation == "missing_tier":
        del dimensions[f"{TERM}.TEST1"]
    elif mutation in {"gap", "overlap"}:
        dimensions[f"{TERM}.TEST1"]["beginRange"] = "101" if mutation == "gap" else "99"
    elif mutation == "ambiguous_offer":
        offers["another"] = copy.deepcopy(offers[TERM])
    elif mutation == "currency":
        dimensions[f"{TERM}.TEST0"]["pricePerUnit"]["CNY"] = "0.1"
    else:
        data.payload["products"][SKU]["attributes"]["taxIncluded"] = "true"
    data.rewrite_catalog()
    with pytest.raises(ValueError):
        data.plan()


def test_missing_compute_claim_is_not_replaced_by_general_principles(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = seed(session, tmp_path, monkeypatch, product="ec2")
    data.references = [ref for ref in data.references if ref.kind != "compute_running_lifecycle"]
    with pytest.raises(ValueError, match="claim set"):
        data.plan()


@pytest.mark.parametrize("mutation", ["country", "region_market", "partition", "provider_inactive"])
def test_live_database_scope_is_part_of_proof(data: Data, mutation: str) -> None:
    plan = data.plan()
    region = data.session.scalars(select(Region)).one()
    if mutation == "country":
        region.country_code = "CN"
    elif mutation == "region_market":
        region.market_mode = "domestic"
    elif mutation == "partition":
        assert region.cloud_partition is not None
        region.cloud_partition.partition_code = "aws_cn"
    else:
        data.snapshot.source_document.provider.is_active = False
    data.session.commit()
    with pytest.raises(ValueError):
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)


def test_documents_can_expire_while_catalog_is_fresh(data: Data) -> None:
    plan = data.plan()
    row = data.session.get(SnapshotRecord, data.document_snapshots[PRINCIPLES])
    assert row is not None
    old = NOW - timedelta(days=8)
    row.captured_at = row.source_document.captured_at = old
    path = data.root / row.manifest_path
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["captured_at"] = old.isoformat()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    data.entries[PRINCIPLES] = data.entries[PRINCIPLES].model_copy(
        update={
            "reviewed_at": NOW - timedelta(days=10),
            "robots_checked_at": NOW - timedelta(days=10),
        }
    )
    data.session.commit()
    with pytest.raises(ValueError):
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)


def test_hash_covers_unselected_catalog_content(data: Data) -> None:
    plan = data.plan()
    path = data.root / data.snapshot.storage_path
    raw = path.read_bytes()
    changed = raw.replace(b"SYNTHETIC TEST ONLY", b"TAMPERING TEST NOW!")
    assert changed != raw and len(changed) == len(raw)
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="integrity"):
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tax_rate", 0),
        ("tax_status", "tax_exempt"),
        ("customer_payable_tax", "zero"),
        ("customer_eligible", True),
        ("complete_tco", True),
        ("lifecycle_activation_granted", True),
    ],
)
def test_rehashed_derived_claim_tampering_is_not_authorization(
    data: Data, field: str, value: Any
) -> None:
    plan = data.plan()
    row = plan["rows"][0]
    payload = json.loads(row["evidence"]["excerpt"])
    payload[field] = value
    row["evidence"]["excerpt"] = billing.canonical(payload)
    row["evidence"]["content_hash"] = billing.digest(row["evidence"]["excerpt"])
    rehash(plan)
    with pytest.raises(ValueError, match="changed"):
        adapter.validate_document_catalog_plan(data.session, plan, raw_root=data.root, as_of=NOW)


@pytest.mark.parametrize("key", ["price_sku_id", "evidence_id"])
def test_valid_but_wrong_foreign_key_target_is_rejected(data: Data, key: str) -> None:
    plan = data.plan()
    ids = persist_synthetic(data, plan)
    first, second = [data.session.get(PriceSnapshot, value) for value in ids]
    assert first is not None and second is not None
    if key == "evidence_id":
        first.evidence_id = second.evidence_id
    else:
        attrs = {**plan["rows"][0]["sku"], "provider_price_code": "other-synthetic-sku"}
        other = PriceSKU(**attrs)
        data.session.add(other)
        data.session.flush()
        first.price_sku_id = other.id
    data.session.commit()
    with pytest.raises(ValueError):
        adapter.validate_document_catalog_prices(
            data.session, plan, price_snapshot_ids=ids, raw_root=data.root, as_of=NOW
        )


def test_reference_hash_requires_actual_pin_and_forbids_extra_fields() -> None:
    for value in (
        {"kind": "general_tax_exclusion", "evidence_id": 1},
        {"kind": "general_tax_exclusion", "evidence_id": True, "content_hash": "a" * 64},
        {
            "kind": "general_tax_exclusion",
            "evidence_id": 1,
            "content_hash": "a" * 64,
            "approved": True,
        },
    ):
        with pytest.raises(ValueError):
            adapter.DocumentPolicyReference.model_validate(value)
