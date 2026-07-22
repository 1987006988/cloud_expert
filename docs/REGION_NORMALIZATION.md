# Region Normalization

Week 6 does not merge provider Regions or declare geographic equivalence.
Existing Region and Zone tables remain provider-scoped.

## Current Region Model

| Entity | Current role |
| --- | --- |
| `CloudPartition` | Provider partition such as AWS commercial or Aliyun public China. |
| `Region` | Provider-specific Region code, country, geography, and market mode. |
| `AvailabilityZone` | Provider-specific Zone code under a Region. |
| `Availability` | Product-level Region availability. |
| `ZoneAvailability` | Product-level Zone availability. |

## Normalization Policy

- Keep `market_mode=domestic` and `market_mode=international` separate.
- Keep provider partition codes separate.
- Do not infer equivalence from similar city names or geography labels.
- Do not use product-level Region/Zone availability as SKU-, family-,
  service-tier-, or feature-level availability proof.

## Known Week 6 Limits

- Huawei Cloud Week 3 acceptance data still has no normalized `Region` rows.
- AWS data is commercial international scope.
- Aliyun data is domestic public China scope.
- Region normalization is a readiness layer for future review, not a mapping
  system.

