# Fresh PostgreSQL Migration

Generated at: 2026-07-22T23:02:12+08:00

## Database

`cloud_expert_r011_fresh`

## Commands

```powershell
.\.venv312\Scripts\python.exe -m alembic -x database_url=<redacted fresh URL> upgrade head
.\.venv312\Scripts\python.exe -m alembic -x database_url=<redacted fresh URL> current
.\.venv312\Scripts\python.exe -m alembic -x database_url=<redacted fresh URL> heads
```

## Result

`FRESH_UPGRADE_HEAD=PASSED`

Alembic applied the full chain:

```text
<base> -> 0001_initial_product_data_model
0001_initial_product_data_model -> 0002_ingestion_snapshots
0002_ingestion_snapshots -> 0003_week03_parsing_models
0003_week03_parsing_models -> 0004_week04_aws_partition_availability
0004_week04_aws_partition_availability -> 0005_week05_aliyun_zone_availability
0005_week05_aliyun_zone_availability -> 0006_week06_canonical_normalization
```

Current revision:

```text
0006_week06_canonical_normalization (head)
```

Head count:

```text
1
```

## Schema Evidence

`schema_after_first_upgrade.json` confirms:

- `dialect = postgresql`
- `alembic_versions = ["0006_week06_canonical_normalization"]`
- `alembic_version.version_num = VARCHAR(128)`
- 35 tables including `alembic_version`
- check constraints, unique constraints, foreign keys, and indexes present
- `postgres_enums = []`

The absence of native PostgreSQL enum types is expected for the current model:
enum-like values are represented as `VARCHAR` columns plus check constraints.
