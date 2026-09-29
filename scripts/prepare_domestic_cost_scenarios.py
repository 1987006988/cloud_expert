"""Pin existing verified components to explicit internal research architectures."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.database.models.pricing import PriceSnapshot
from cloud_expert.database.models.source import Evidence
from cloud_expert.database.session import SessionLocal
from cloud_expert.pricing.scoped_tco import OPTIONAL_DIMENSIONS, ScopedECSConfig, snapshot_scope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--aliyun-fixed-ip-policy", type=int)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with SessionLocal() as session:
        for provider, snapshots, policies, period, disk_unit in (
            (
                "huawei_cloud",
                (7, 8, 9),
                {
                    "support": (14195, "huawei_basic_support"),
                    "ip_holding": (14196, "huawei_bound_eip"),
                },
                730,
                "GB",
            ),
            ("aliyun", (10, 11, 12), {"support": (14200, "aliyun_basic_support")}, 720, "GiB"),
        ):
            if provider == "aliyun" and args.aliyun_fixed_ip_policy:
                policies["ip_holding"] = (args.aliyun_fixed_ip_policy, "aliyun_instance_fixed_ipv4")
            prices = [session.get(PriceSnapshot, key) for key in snapshots]
            if any(price is None for price in prices):
                raise ValueError("pinned component is missing")
            first = prices[0]
            assert first is not None
            product = first.price_sku.product
            if product.provider.code != provider:
                raise ValueError("pinned component provider differs")
            costs = []
            for dimension, price in zip(
                ("compute", "system_disk", "outbound"), prices, strict=True
            ):
                assert price is not None
                costs.append(
                    {
                        "dimension": dimension,
                        "treatment": "price",
                        "quantity": str(price.minimum_quantity),
                        "unit": price.price_sku.billing_unit,
                        "rationale": "Use only the exact captured quantity and duration; no extrapolation.",
                        "price_snapshot_id": price.id,
                        "evidence_sha256": price.evidence.content_hash,
                        "expected_price_scope": snapshot_scope(session, price),
                    }
                )
            for dimension, (key, code) in policies.items():
                evidence = session.get(Evidence, key)
                if evidence is None:
                    raise ValueError("pinned policy evidence is missing")
                costs.append(
                    {
                        "dimension": dimension,
                        "treatment": "policy_zero",
                        "quantity": "1",
                        "unit": "scenario",
                        "rationale": "Apply the official basic support or fully bound IP policy only within its validated conditions.",
                        "evidence_id": key,
                        "evidence_sha256": evidence.content_hash,
                        "policy_code": code,
                    }
                )
            if provider == "aliyun" and not args.aliyun_fixed_ip_policy:
                costs.append(
                    {
                        "dimension": "ip_holding",
                        "treatment": "missing",
                        "quantity": "1",
                        "unit": "scenario",
                        "rationale": "Instance-assigned public IPv4 holding-charge policy is not yet captured; do not reuse Huawei EIP policy.",
                    }
                )
            for dimension in OPTIONAL_DIMENSIONS:
                costs.append(
                    {
                        "dimension": dimension,
                        "treatment": "not_applicable",
                        "quantity": "0",
                        "unit": "scenario",
                        "rationale": f"{dimension} is not deployed or purchased in this single-instance infrastructure-only research architecture; this is not a full business ownership-cost claim.",
                    }
                )
            config = ScopedECSConfig.model_validate(
                {
                    "scenario_code": f"{provider}_ecs_bounded_infrastructure_{period}h",
                    "scenario_version": "v3_fixed_ipv4_20260930"
                    if provider == "aliyun" and args.aliyun_fixed_ip_policy
                    else "v2_20260930",
                    "name": f"{provider} ECS explicit {period}h infrastructure research",
                    "context": {
                        "provider_id": product.provider_id,
                        "product_id": product.id,
                        "provider_code": provider,
                        "partition": "huawei_cn"
                        if provider == "huawei_cloud"
                        else "aliyun_public_cn",
                        "region": first.price_sku.region.code,
                        "duration_hours": str(period),
                        "support_plan": "basic",
                        "eip_binding": "bound" if provider == "huawei_cloud" else "not_deployed",
                        "eip_bound_hours": str(period) if provider == "huawei_cloud" else "0",
                    },
                    "price_basis": "official_bounded_quote"
                    if provider == "huawei_cloud"
                    else "catalog_reference",
                    "disk_capacity": "100",
                    "disk_capacity_unit": disk_unit,
                    "outbound_gb": "100",
                    "outbound_cap_mbps": "5" if provider == "huawei_cloud" else None,
                    "architecture_description": "One Linux VM, one priced 100-unit system disk, 100 GB public egress, basic support. Huawei EIP remains bound for the entire quote. Aliyun uses instance-assigned public IPv4, not independent EIP. No optional infrastructure services are deployed. Operations and migration labor are outside this infrastructure cost boundary, not priced as free. No vendor equivalence or resource availability is asserted.",
                    "enabled_optional_costs": [],
                    "costs": costs,
                }
            )
            path = args.output_dir / f"{provider}.json"
            path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            print(path)
        session.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
