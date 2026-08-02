# Week 9 Pricing Source Review

Review date: 2026-07-23

Scope: Huawei Cloud ECS/OBS, AWS EC2/S3, and Aliyun ECS/OSS official pricing
sources for internal pricing/TCO engineering.

## Source Review Result

| Source | Provider/Product | Collection mode | Result |
| --- | --- | --- | --- |
| `huawei_cloud_ecs_pricing` | Huawei Cloud ECS | automated HTTP snapshot | Approved and captured |
| `huawei_cloud_ecs_on_demand_example` | Huawei Cloud ECS | automated HTTP snapshot | Approved and captured as billing-method evidence |
| `huawei_cloud_obs_pricing` | Huawei Cloud OBS | automated HTTP snapshot | Approved and captured |
| `aws_ec2_pricing_on_demand` | AWS EC2 | automated HTTP snapshot | Approved and captured |
| `aws_s3_pricing` | AWS S3 | automated HTTP snapshot | Approved and captured |
| `aws_s3_pricing_bulk_us_east_1` | AWS S3 | automated structured JSON snapshot | Approved, captured, and parsed |
| `aliyun_ecs_pricing` | Aliyun ECS | manual/browser snapshot required | Approved for manual/browser capture only |
| `aliyun_oss_pricing` | Aliyun OSS | manual/browser snapshot required | Approved for manual/browser capture only |
| `aliyun_oss_billing_overview_pricing` | Aliyun OSS | automated HTTP snapshot | Approved and captured as billing-method evidence |
| `aliyun_oss_storage_fees_pricing` | Aliyun OSS | automated HTTP snapshot | Approved and captured as storage-fee evidence |

## Structured Price Output

One `PriceSKU` and one `PriceSnapshot` were created from the official AWS Price
List Bulk API regional snapshot:

| Provider/Product | Region | Billing unit | Unit price | Currency | Discount type |
| --- | --- | --- | ---: | --- | --- |
| `aws/s3` | `us-east-1` | `GB-month` | `0.0230000000` | USD | list |

The price is linked to a pricing `SourceDocument`, `SnapshotRecord`, and
`Evidence` row. The local immutable raw snapshot path is listed in
`reports/week09_pricing/snapshot_manifest.json`.

## TCO Output

The internal TCO scenario `internal_price_readiness_storage_1tb_month` generated
six line items. AWS S3 standard storage for 1024 GB-months is priced at
`23.55200000 USD`. The other five dimensions remain missing because no official
snapshot currently contains enough product, region, unit, currency, and numeric
price scope for `PriceSnapshot`.

Missing prices are represented as `NULL` amounts with `missing_reason`; they are
not treated as zero.

## Deliverables

- `reports/week09_pricing/source_audit.md`
- `reports/week09_pricing/snapshot_manifest.json`
- `reports/week09_pricing/price_records.json`
- `reports/week09_pricing/tco_detail.md`
- `reports/week09_gate/gate_summary.md`

