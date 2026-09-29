"""Synthetic-only AWS promotion safety tests; no business writes or external calls."""

import copy
import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cloud_expert.database.base import Base
from cloud_expert.database.models.cloud_partition import CloudPartition
from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.product import Product, ProductCategory
from cloud_expert.database.models.region import Region
from cloud_expert.database.models.source import Evidence
from cloud_expert.pricing import aws_billing_policy as policies
from cloud_expert.pricing import aws_catalog_promotion as promotion
from tests.unit.test_aws_billing_policy import HTML, policy_entry, provider, store_snapshot
from tests.unit.test_official_catalog import NOW, SKU, TERM, fixture


def seed(session, root, monkeypatch, *, product="s3", request=False, first_price="0.1234567800"):
    owner = provider(session)
    category = ProductCategory(code="synthetic", name="Synthetic only")
    partition = CloudPartition(
        provider_id=owner.id,
        partition_code="aws",
        partition_name="Synthetic AWS",
        market_mode="international",
        is_active=True,
    )
    session.add_all([category, partition])
    session.flush()
    item = Product(
        provider_id=owner.id,
        category_id=category.id,
        code=product,
        market_mode="international",
        official_name="SYNTHETIC ONLY",
        display_name="Synthetic only",
        product_status="unknown",
    )
    region = Region(
        provider_id=owner.id,
        code="us-east-1",
        name="Synthetic region",
        country_code="US",
        market_mode="international",
        is_active=True,
        cloud_partition_id=partition.id,
    )
    session.add_all([item, region])
    session.flush()
    entry, payload, selection = fixture("AmazonS3" if product == "s3" else "AmazonEC2")
    dimensions = payload["terms"]["OnDemand"][SKU][TERM]["priceDimensions"]
    dimensions[f"{TERM}.TEST0"]["pricePerUnit"]["USD"] = first_price
    if request:
        attrs = {**selection.attributes, "group": "S3-API-Tier1", "usagetype": "Requests-Tier1"}
        selection = selection.model_copy(
            update={"attributes": attrs, "product_family": "API Request", "unit": "Requests"}
        )
        payload["products"][SKU].update(productFamily="API Request", attributes=attrs)
        for row in dimensions.values():
            row["unit"] = "Requests"
        dimensions[f"{TERM}.TEST0"]["pricePerUnit"]["USD"] = "0.0000050000"
    snapshot = store_snapshot(session, root, entry, json.dumps(payload).encode(), owner)
    policy = policy_entry(product)
    policy_snapshot = store_snapshot(session, root, policy, HTML.encode(), owner)
    entries = {entry.source_id: entry, policy.source_id: policy}
    monkeypatch.setattr(policies, "get_entry_by_source_id", entries.get)
    session.commit()
    return {
        "snapshot": snapshot,
        "policy": policy_snapshot,
        "selection": selection,
        "root": root,
        "region": region,
        "payload": payload,
        "entries": entries,
        "provider": owner,
    }


@pytest.fixture
def data(session, tmp_path, monkeypatch):
    return seed(session, tmp_path, monkeypatch)


def plan(session, data):
    return promotion.prepare_aws_catalog_promotion(
        session,
        snapshot_id=data["snapshot"].id,
        policy_snapshot_id=data["policy"].id,
        selections=[data["selection"]],
        raw_root=data["root"],
        as_of=NOW,
    )


def apply(session, data, proposal, **kwargs):
    return promotion.apply_aws_catalog_promotion(
        session, proposal, raw_root=data["root"], now=NOW, **kwargs
    )


def test_dryrun_full_tiers_exact_raw_paths_tax_and_no_approval(session, data):
    proposal = plan(session, data)
    assert len(proposal["rows"]) == 2
    first, second = proposal["rows"]
    assert first["price"]["unit_price"] == "0.1234567800"
    assert first["price"]["maximum_quantity"] == second["price"]["minimum_quantity"] == "100"
    assert second["price"]["maximum_quantity"] is None
    assert first["sku"]["billing_unit"] == "GiB-month" and first["sku"]["sku_id"] is None
    assert first["sku"]["tax_included"] is False
    payload = json.loads(first["evidence"]["excerpt"])
    assert payload["raw_sha256"] == data["snapshot"].content_hash
    assert payload["catalog_record"]["price_locator"] == first["evidence"]["locator"]
    assert payload["customer_payable_tax"] == "unknown" and payload["hours_per_month"] is None
    result = apply(session, data, proposal)
    assert result["prices_planned"] == 2 and result["price_snapshots_created"] == 0
    assert not result["customer_eligible"] and not result["complete_tco"]
    assert session.scalar(select(func.count()).select_from(Evidence)) == 0


def test_apply_idempotence_and_revalidation_at_consumption(session, data):
    proposal = plan(session, data)
    result = apply(session, data, proposal, apply=True)
    assert result["price_snapshots_created"] == 2 and result["price_skus_created"] == 1
    assert result["evidence_created"] == 6 and len(result["policy_evidence_ids"]) == 4
    assert not result["transaction_committed"] and result["approvals_granted"] == 0
    session.commit()
    retry = apply(session, data, proposal, apply=True)
    assert retry["price_snapshots_created"] == retry["evidence_created"] == 0
    assert retry["existing_prices"] == 2
    session.commit()
    price = session.get(PriceSnapshot, result["links"][0]["price_snapshot_id"])
    assert price.unit_price == Decimal("0.12345678")
    assert promotion.aws_catalog_price_valid(session, price, raw_root=data["root"], now=NOW)
    policy = session.get(Evidence, result["policy_evidence_ids"][0])
    policy.review_status = "rejected"
    session.commit()
    assert not promotion.aws_catalog_price_valid(session, price, raw_root=data["root"], now=NOW)


@pytest.mark.parametrize("kind", ["caller", "injected"])
def test_atomic_rollback(session, data, monkeypatch, kind):
    proposal = plan(session, data)
    if kind == "injected":
        original = promotion.evidence_row

        def fail(session, row, *, apply=False):
            result = original(session, row, apply=apply)
            if apply and row["parser_rule"] == promotion.RULE:
                raise RuntimeError("synthetic after write")
            return result

        monkeypatch.setattr(promotion, "evidence_row", fail)
        with pytest.raises(RuntimeError):
            apply(session, data, proposal, apply=True)
        session.commit()
    else:
        apply(session, data, proposal, apply=True)
        session.rollback()
    for cls in (Evidence, PriceSKU, PriceSnapshot):
        assert session.scalar(select(func.count()).select_from(cls)) == 0


@pytest.mark.parametrize("mutation", ["price", "sku", "evidence", "duplicate_price", "policy"])
def test_immutable_conflict_never_overwrites_history(session, data, mutation):
    proposal = plan(session, data)
    result = apply(session, data, proposal, apply=True)
    session.commit()
    price = session.get(PriceSnapshot, result["links"][0]["price_snapshot_id"])
    if mutation == "price":
        price.unit_price = Decimal("99")
    elif mutation == "sku":
        price.price_sku.tax_included = True
    elif mutation == "evidence":
        price.evidence.content_hash = "0" * 64
    elif mutation == "policy":
        session.get(Evidence, result["policy_evidence_ids"][0]).review_status = "rejected"
    else:
        session.add(
            PriceSnapshot(
                price_sku_id=price.price_sku_id,
                evidence_id=price.evidence_id,
                **promotion._price_values(proposal["rows"][0]),
            )
        )
    session.commit()
    with pytest.raises(ValueError):
        apply(session, data, proposal, apply=True)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Evidence)) == 6
    assert not promotion.aws_catalog_price_valid(session, price, raw_root=data["root"], now=NOW)


@pytest.mark.parametrize(
    "mutation",
    ["region", "country", "partition", "stale", "raw", "manifest", "tax", "selection", "currency"],
)
def test_scope_provenance_and_replay_guards(session, data, mutation):
    proposal = plan(session, data)
    if mutation == "region":
        data["region"].market_mode = "domestic"
    elif mutation == "country":
        data["region"].country_code = "CN"
    elif mutation == "partition":
        data["region"].cloud_partition.partition_code = "aws_cn"
    elif mutation == "stale":
        data["snapshot"].is_current = False
    elif mutation == "raw":
        path = data["root"] / data["snapshot"].storage_path
        path.write_bytes(b"X" * path.stat().st_size)
    elif mutation == "manifest":
        (data["root"] / data["snapshot"].manifest_path).write_text("{}")
    elif mutation == "tax":
        path = data["root"] / data["policy"].storage_path
        path.write_bytes(b"X" * path.stat().st_size)
    else:
        proposal["config"]["selections"][0]["currency" if mutation == "currency" else "sku"] = "CNY"
        proposal["plan_sha256"] = policies.digest(
            policies.canonical({k: v for k, v in proposal.items() if k != "plan_sha256"})
        )
    session.commit()
    with pytest.raises(ValueError):
        apply(session, data, proposal, apply=True)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(PriceSnapshot)) == 0


@pytest.mark.parametrize("value", ["0.123456789", "10000000000000000", "-0.1", "NaN", "Infinity"])
def test_decimal_precision_cannot_be_silently_truncated(value):
    with pytest.raises(ValueError):
        promotion.decimal8(value)


def test_expiry_and_plan_tampering_fail_without_writes(session, data):
    proposal = plan(session, data)
    with pytest.raises(ValueError):
        promotion.apply_aws_catalog_promotion(
            session, proposal, raw_root=data["root"], now=NOW + timedelta(days=8), apply=True
        )
    bad = copy.deepcopy(proposal)
    bad["rows"][0]["price"]["unit_price"] = "0"
    with pytest.raises(ValueError, match="plan hash"):
        apply(session, data, bad, apply=True)
    bad["plan_sha256"] = policies.digest(
        policies.canonical({k: v for k, v in bad.items() if k != "plan_sha256"})
    )
    with pytest.raises(ValueError, match="inputs changed"):
        apply(session, data, bad, apply=True)


@pytest.mark.parametrize(
    "product,is_request,unit", [("ec2", False, "instance-hour"), ("s3", True, "request")]
)
def test_compute_and_request_units_without_fake_hour_or_1000_conversion(
    session, tmp_path, monkeypatch, product, is_request, unit
):
    data = seed(session, tmp_path, monkeypatch, product=product, request=is_request)
    proposal = plan(session, data)
    assert proposal["rows"][0]["sku"]["billing_unit"] == unit
    if is_request:
        assert proposal["rows"][0]["price"]["unit_price"] == "0.0000050000"
    else:
        payload = json.loads(proposal["rows"][0]["evidence"]["excerpt"])
        assert payload["catalog_record"]["product_attributes"]["instanceType"] == "synthetic.xlarge"
    assert apply(session, data, proposal, apply=True)["price_snapshots_created"] == 2


def test_data_transfer_zero_is_quarantined_not_promoted(session, data):
    data["selection"] = data["selection"].model_copy(
        update={"product_family": "Data Transfer", "unit": "GB"}
    )
    with pytest.raises(ValueError, match="quarantined"):
        plan(session, data)
    assert session.scalar(select(func.count()).select_from(PriceSKU)) == 0


def test_sqlite_concurrent_promotion_serializes_and_retries(tmp_path, monkeypatch):
    db = create_engine(f"sqlite:///{tmp_path / 'synthetic.sqlite'}", connect_args={"timeout": 0.1})
    Base.metadata.create_all(db)
    with Session(db) as first, Session(db) as second:
        data = seed(first, tmp_path / "raw", monkeypatch)
        proposal = plan(first, data)
        first.rollback()
        apply(first, data, proposal, apply=True)
        with pytest.raises(OperationalError, match="locked"):
            apply(second, data, proposal, apply=True)
        second.rollback()
        first.commit()
        assert apply(second, data, proposal, apply=True)["existing_prices"] == 2
        second.commit()
    db.dispose()


def test_one_unrepresentable_tier_blocks_the_whole_import(session, tmp_path, monkeypatch):
    data = seed(session, tmp_path, monkeypatch, first_price="0.123456789")
    with pytest.raises(ValueError, match="Numeric"):
        plan(session, data)
    for cls in (Evidence, PriceSKU, PriceSnapshot):
        assert session.scalar(select(func.count()).select_from(cls)) == 0


def test_sqlite_numeric_storage_loss_rolls_back_instead_of_silently_changing_price(
    session, tmp_path, monkeypatch
):
    data = seed(session, tmp_path, monkeypatch, first_price="9999999999999999.00000000")
    proposal = plan(session, data)
    with pytest.raises(ValueError, match="PriceSnapshot conflict"):
        apply(session, data, proposal, apply=True)
    session.commit()
    for cls in (Evidence, PriceSKU, PriceSnapshot):
        assert session.scalar(select(func.count()).select_from(cls)) == 0


def test_missing_policy_evidence_or_tier_is_not_valid_consumption(session, data):
    proposal = plan(session, data)
    result = apply(session, data, proposal, apply=True)
    session.commit()
    first = session.get(PriceSnapshot, result["links"][0]["price_snapshot_id"])
    other = session.get(PriceSnapshot, result["links"][1]["price_snapshot_id"])
    session.delete(other)
    session.commit()
    assert not promotion.aws_catalog_price_valid(session, first, raw_root=data["root"], now=NOW)
    apply(session, data, proposal, apply=True)
    session.commit()
    session.delete(session.get(Evidence, result["policy_evidence_ids"][0]))
    session.commit()
    assert not promotion.aws_catalog_price_valid(session, first, raw_root=data["root"], now=NOW)


def test_missing_policy_snapshot_dirty_session_and_unsupported_units(session, data):
    original_id = data["policy"].id
    with pytest.raises(ValueError, match="snapshot missing"):
        promotion.prepare_aws_catalog_promotion(
            session,
            snapshot_id=data["snapshot"].id,
            policy_snapshot_id=999999,
            selections=[data["selection"]],
            raw_root=data["root"],
            as_of=NOW,
        )
    assert data["policy"].id == original_id
    data["region"].name = "uncommitted"
    with pytest.raises(ValueError, match="clean"):
        plan(session, data)
    session.rollback()
    for updates in [{"attributes": {"volumeType": "Glacier"}}, {"product_family": "Other"}]:
        with pytest.raises(ValueError):
            promotion._units(data["selection"].model_copy(update=updates), "s3")


def test_cli_readonly_saved_plan_apply_replay_and_immutable_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import promote_aws_catalog as cli

    class Clock:
        @staticmethod
        def now(_):
            return NOW

    monkeypatch.setattr(cli, "datetime", Clock)
    database = tmp_path / "synthetic-cli.sqlite"
    db = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(db)
    with Session(db) as session:
        data = seed(session, tmp_path / "raw", monkeypatch)
        snapshot_id, policy_id = data["snapshot"].id, data["policy"].id
        selection_path = tmp_path / "selection.json"
        selection_path.write_text(json.dumps([data["selection"].model_dump()]))
    db.dispose()
    base = [
        "promote_aws_catalog.py",
        "--database",
        str(database),
        "--raw-root",
        str(tmp_path / "raw"),
    ]
    preview = tmp_path / "preview"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            *base,
            "--snapshot",
            str(snapshot_id),
            "--policy-snapshot",
            str(policy_id),
            "--selection",
            str(selection_path),
            "--report-dir",
            str(preview),
        ],
    )
    assert cli.main() == 0
    result = json.loads((preview / "result.json").read_text())
    assert result["database_open_mode"] == "ro" and result["price_snapshots_created"] == 0
    with pytest.raises(FileExistsError):
        cli.main()
    for directory, expected in [("apply", 2), ("retry", 0)]:
        target = tmp_path / directory
        monkeypatch.setattr(
            sys,
            "argv",
            [*base, "--plan", str(preview / "plan.json"), "--apply", "--report-dir", str(target)],
        )
        assert cli.main() == 0
        result = json.loads((target / "result.json").read_text())
        assert result["transaction_committed"] and result["price_snapshots_created"] == expected
        assert result["customer_eligible"] is False
    bad_plan = tmp_path / "bad.json"
    bad_plan.write_text("{}")
    target = tmp_path / "blocked"
    monkeypatch.setattr(sys, "argv", [*base, "--plan", str(bad_plan), "--report-dir", str(target)])
    with pytest.raises(ValueError):
        cli.main()
    assert json.loads((target / "failure.json").read_text())["status"] == "blocked"
    monkeypatch.setattr(sys, "argv", [*base, "--apply", "--report-dir", str(tmp_path / "no-plan")])
    with pytest.raises(SystemExit):
        cli.main()
    capsys.readouterr()
