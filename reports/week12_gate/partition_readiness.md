# Provider Partition Readiness

## Database Partitions

| Provider | Partition | Market mode | Status |
| --- | --- | --- | --- |
| AWS | `aws` | international | Present; represents commercial scope but is not named `aws_commercial` |
| Aliyun | `aliyun_public_cn` | domestic | Present |
| Huawei Cloud | none | unknown | Missing from database |

## Required Week 12 Partitions

| Required partition | Readiness |
| --- | --- |
| AWS Commercial | Partial: existing `aws` partition requires explicit compatibility decision |
| AWS China | Missing |
| Aliyun China public cloud | Present |
| Aliyun International | Missing |
| Huawei Cloud China | Registry mentions `huawei_cn` in 3 entries, but database partition is missing |
| Huawei Cloud International | Missing |

Partition validation cannot be declared ready because:

- only 2 partition rows exist for 3 providers;
- 24 registry entries omit `cloud_partition`;
- 21 SourceDocuments have no partition value;
- country, region, and effective scope fields are absent from every registry entry;
- `scripts/validate_market_partitions.py` does not exist;
- AWS China, Aliyun International, and both Huawei commercial partitions are not fully modeled.

Historical rows must remain unknown where scope cannot be proven. No migration or inferred backfill
was performed while Week 11 remains NO-GO.
