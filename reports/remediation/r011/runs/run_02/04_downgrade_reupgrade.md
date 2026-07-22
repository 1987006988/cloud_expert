# Downgrade And Re-Upgrade

Generated at: 2026-07-22T23:02:12+08:00

## Single-Step Downgrade

Database: `cloud_expert_r011_fresh`

```powershell
alembic -x database_url=<redacted fresh URL> downgrade -1
alembic -x database_url=<redacted fresh URL> current
alembic -x database_url=<redacted fresh URL> upgrade head
```

Result:

```text
downgrade -1: passed
current after downgrade: 0005_week05_aliyun_zone_availability
re-upgrade head: passed
```

## Full Downgrade And Re-Upgrade

Database: `cloud_expert_r011_full`

```powershell
alembic -x database_url=<redacted full URL> upgrade head
alembic -x database_url=<redacted full URL> downgrade base
alembic -x database_url=<redacted full URL> upgrade head
```

Result:

```text
initial upgrade head: passed
downgrade base: passed
tables after downgrade base: ["alembic_version"]
re-upgrade head: passed
```

The base downgrade left no application tables behind. Keeping
`alembic_version` is expected Alembic behavior.

## Direct Fix Validated

PostgreSQL previously failed when writing long Alembic revision IDs into the
default `alembic_version.version_num VARCHAR(32)` column. Migration `0004` now
widens this column to `VARCHAR(128)` before writing the first long revision ID.

This was validated by both fresh upgrade and re-upgrade from base.
