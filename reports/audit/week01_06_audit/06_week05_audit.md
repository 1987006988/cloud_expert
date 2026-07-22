# Week05 Audit

## Verdict

**PASS_WITH_RISK.** Aliyun ECS/OSS domestic baseline is evidence-backed and market/zone validation passes, but review remains incomplete.

## Verified Counts

- Source documents: 24.
- Snapshot records: 24.
- Ingestion runs: 24.
- Parsing runs: 24.
- Evidence records: 8039.
- Product specifications: 6311.
- ECS SKUs: 994.
- ECS product families: 208.
- OSS service tiers: 5.
- Regions: 19.
- Availability rows: 34.
- Availability zones: 62.
- Zone availability rows: 62.
- Review items: 82.

## Validation

- `validate_source_registry.py --provider aliyun`: 26 valid, 2 disabled, 0 errors.
- `validate_provider_market_scope.py --provider aliyun`: 0 errors.
- `validate_region_zone_relationships.py --provider aliyun`: 0 errors.
- `validate_provider_partitions.py --provider aliyun`: 0 violations.

## Risks

- 82 open review items.
- Zone/Region availability is product-level only and cannot prove SKU-level or storage-class-level availability.
