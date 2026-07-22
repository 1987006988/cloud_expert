# Aliyun Provider Notes

Week 5 registers and parses Aliyun China public cloud sources for Elastic
Compute Service and Object Storage Service in domestic mode.

Provider scope:

- `provider_code=aliyun`
- `market_mode=domestic`
- `cloud_partition=aliyun_public_cn`
- Official hosts: `www.aliyun.com`, `cn.aliyun.com`, `help.aliyun.com`, and
  `terms.aliyun.com`

Hong Kong, overseas, finance/special partitions, government cloud, account
console pages, AccessKey/API calls, cookies, private endpoints, and
`alibabacloud.com` international pages are out of Week 5 scope.

## Source Registration

Twenty-six Aliyun source registry records are checked in:

| Product | Enabled | Disabled/manual-only pricing | Registry path |
| --- | ---: | ---: | --- |
| ECS | 9 | 1 | `data/source_registry/domestic/aliyun/ecs/` |
| OSS | 15 | 1 | `data/source_registry/domestic/aliyun/oss/` |

Pricing URLs are retained only as disabled manual-review placeholders. They are
not fetched, parsed, or used for product facts.

## Data Boundary

- Product facts must trace to `SourceDocument`, `SnapshotRecord`, and
  `Evidence`.
- ECS instance types are represented as `SKU`; ECS instance families are
  represented as `ProductFamily`.
- OSS storage classes are represented as `ServiceTier`.
- ECS Region and Zone pages create product-level `AvailabilityZone` and
  `ZoneAvailability` rows. They do not prove SKU-level availability.
- OSS Region pages create product-level `Availability` rows. They do not prove
  storage-class-level Region availability.

## Acceptance Metrics

The Week 5 Aliyun acceptance database is
`test_outputs/week5_aliyun_acceptance_v2.sqlite`.

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
| Partition violations | 0 | 0 |
