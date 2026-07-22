# Data Quality

## Quality Gates

Week 3 validation covers:

- Source registry validation by provider, product, and domestic market mode.
- Raw snapshot manifest validation.
- Evidence link validation from normalized facts back to source evidence.
- Parser unit tests with synthetic Huawei-like fixtures.
- End-to-end snapshot-to-parse tests.
- Quality report generation by provider and product.
- Manual review sample generation with blank reviewer fields.
- Alembic upgrade, downgrade, and re-upgrade checks on a fresh database.
- Ruff, mypy, pytest, and coverage checks.

Week 4 adds:

- AWS commercial partition validation.
- AWS EC2/S3 source registry validation.
- AWS EC2/S3 official snapshot ingestion and raw manifest validation.
- AWS EC2/S3 parser fixtures and pipeline tests.
- Product-level Region and Availability evidence-link checks.

Week 5 adds:

- Aliyun domestic public cloud market-scope validation.
- Aliyun ECS/OSS source registry validation.
- Aliyun ECS/OSS official snapshot ingestion and raw manifest validation.
- Aliyun ECS/OSS parser fixtures and pipeline tests.
- Product-level Region, Zone, Availability, and ZoneAvailability evidence-link
  checks.

## Acceptance Reports

Reports are generated under `data/reports/`.

| Report | Product | Key result |
| --- | --- | --- |
| `huawei_cloud_ecs_quality.json` | ECS | 37 SKUs, 17 families, 2 SLA records, 268 evidence records, 7 open review items, 0 missing evidence links. |
| `huawei_cloud_obs_quality.json` | OBS | 4 service tiers, 5 SLA records, 83 evidence records, 2 open review items, 0 missing evidence links. |
| `aws_ec2_quality.json` | EC2 | 678 SKUs, 74 families, 34 Regions, 2 SLA records, 5012 evidence records, 1349 open review items, 0 missing evidence links. |
| `aws_s3_quality.json` | S3 | 8 service tiers, 34 Regions, 1 SLA record, 711 evidence records, 1 open review item, 0 missing evidence links. |
| `aliyun_ecs_quality.json` | ECS | 994 SKUs, 208 families, 15 Regions, 62 Zones, 2 SLA records, 7891 evidence records, 70 open review items, 0 missing evidence links. |
| `aliyun_oss_quality.json` | OSS | 5 service tiers, 19 Regions, 1 SLA record, 148 evidence records, 12 open review items, 0 missing evidence links. |
| `huawei_cloud_review_items.json` | ECS and OBS | 9 open low-confidence review items. |

Manual review sample:

| File | Rows | Notes |
| --- | ---: | --- |
| `reports/review_samples/week03_manual_review_sample.csv` | 66 | `review_result` and `reviewer_notes` are intentionally blank for human reviewers. |
| `reports/review_samples/week04_aws_manual_review_sample.csv` | 125 | AWS reviewer sample with blank review fields. |
| `reports/review_samples/week05_aliyun_manual_review_sample.csv` | 153 | Aliyun reviewer sample with blank review fields. |

## Week 4 AWS Metrics

| Metric | EC2 | S3 |
| --- | ---: | ---: |
| Product records | 1 | 1 |
| SKU records | 678 | 0 |
| Product family records | 74 | 0 |
| Service tier records | 0 | 8 |
| Region records | 34 | 34 |
| Availability records | 34 | 34 |
| SLA records | 2 | 1 |
| Evidence records | 5012 | 711 |
| Review items | 1349 | 1 |
| Missing evidence links | 0 | 0 |
| Partition violations | 0 | 0 |
| Field coverage | 0.6522 | 0.7391 |

## Week 5 Aliyun Metrics

| Metric | ECS | OSS |
| --- | ---: | ---: |
| Product records | 1 | 1 |
| SKU records | 994 | 0 |
| Product family records | 208 | 0 |
| Service tier records | 0 | 5 |
| Region records | 15 | 19 |
| Availability records | 15 | 19 |
| Zone records | 62 | 0 |
| Zone availability records | 62 | 0 |
| SLA records | 2 | 1 |
| Evidence records | 7891 | 148 |
| Review items | 70 | 12 |
| Missing evidence links | 0 | 0 |
| Partition region violations | 0 | 0 |
| Partition zone violations | 0 | 0 |
| Field coverage | 0.7692 | 0.8333 |

## Week 3 Huawei Metrics

| Metric | ECS | OBS |
| --- | ---: | ---: |
| Product records | 1 | 1 |
| SKU records | 37 | 0 |
| Product family records | 17 | 0 |
| Service tier records | 0 | 4 |
| SLA records | 2 | 5 |
| Parsing runs | 9 | 12 |
| Evidence records | 268 | 83 |
| Review items | 7 | 2 |
| Missing evidence links | 0 | 0 |
| Field coverage | 0.55 | 0.8421 |

The combined acceptance database contains 390 parsed field candidates and 228
persisted product specification rows.

## Known Quality Limits

- ECS coverage is intentionally incomplete because some expected GPU, operating
  system, connection, and advanced limit fields are not present in the current
  accepted source snapshots.
- OBS coverage is slightly below the target threshold because retrieval and
  class-specific wording needs review.
- The Week 3 Huawei acceptance database has 0 `Region` rows and 0
  `Availability` rows. Huawei Region pages are retained as product-level
  evidence only until an approved, parseable official region table is added.
- Open review items block customer-facing use of the affected fields.
- Network pytest tests were not run; the official source fetch was executed by
  controlled CLI runs and then parsed offline.
- AWS Region availability is product-level only. It must not be used as proof of
  SKU-, family-, service-tier-, or feature-level availability.
- Aliyun ECS Zone availability is product-level only. It must not be used as
  proof of SKU-, family-, storage-class-, or feature-level availability.
- Aliyun ECS and OSS still have open low-confidence review items. Those fields
  remain evidence-backed but not human-reviewed.

## Week 6 Canonical Normalization Metrics

| Metric | Count |
| --- | ---: |
| Canonical field definitions | 38 |
| Normalization rules | 40 |
| Normalized specifications | 10172 |
| Comparability assessments | 116 |
| Machine-extracted normalized rows | 9404 |
| Pending-review normalized rows | 768 |
| Scope mismatch warnings | 90 |
| Missing normalized evidence links | 0 |
| Average normalization quality score | 0.9781 |

Comparability readiness:

| Status | Count |
| --- | ---: |
| comparable | 13 |
| partial | 66 |
| not_comparable | 37 |

Generated reports are under `reports/normalization/`.

Known Week 6 quality limits:

- 240 input `ProductSpecification` rows were skipped because the standardized
  value could not produce exactly one canonical value.
- 90 object-storage rows fell back from ideal `service_tier` scope to `product`
  scope because the prior product specification table does not persist a direct
  service-tier key.
- Comparability assessments are field-level readiness records only.
