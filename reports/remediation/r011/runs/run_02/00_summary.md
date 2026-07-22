# R011 PostgreSQL Live Validation Run 02 Summary

Generated at: 2026-07-22T23:02:12+08:00

## Verdict

`R011_STATUS=COMPLETED`

`WEEK7_GATE=NO-GO`

R011 live PostgreSQL validation completed successfully against Docker Desktop
PostgreSQL. The previous blocked evidence under `reports/remediation/r011/`
was not overwritten; this run is stored under
`reports/remediation/r011/runs/run_02/`.

## Key Results

| Area | Result |
| --- | --- |
| Docker daemon | running |
| PostgreSQL container | `cloud_expert-postgres-1`, healthy |
| PostgreSQL image | `postgres:16` |
| PostgreSQL server | `PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1)` |
| Published port | `54329 -> 5432` |
| Fresh DB | `cloud_expert_r011_fresh` |
| Full rollback DB | `cloud_expert_r011_full` |
| Test DB | `cloud_expert_r011_tests` |
| Alembic head | `0006_week06_canonical_normalization` |
| Head count | 1 |
| Fresh upgrade | passed |
| Downgrade `-1` | passed |
| Re-upgrade head | passed |
| Downgrade base | passed |
| Re-upgrade from base | passed |
| Schema fingerprints | equal after excluding database URL |
| PostgreSQL integration tests | 6 passed |
| Full non-network tests | 71 passed |
| Coverage | 79%, unchanged R009 issue |
| Ruff format/check | passed |
| Ruff check | passed |
| mypy | passed, 172 source files |

## Direct R011 Fixes

- Added Alembic `-x database_url=...` support so R011 can target isolated
  PostgreSQL databases without changing `DATABASE_URL` globally.
- Fixed PostgreSQL Alembic version table compatibility by widening
  `alembic_version.version_num` to `VARCHAR(128)` during migration `0004`,
  before the first revision ID longer than PostgreSQL's default Alembic
  `VARCHAR(32)` can be written.
- Added `scripts/check_database_connection.py` for SQLAlchemy-level connection,
  identity, pool, commit, and rollback validation.
- Added PostgreSQL marker and live integration tests under
  `tests/integration/test_postgres_r011.py`.
- Enhanced schema inspection to include check constraints, dialect, PostgreSQL
  native enum inventory, and quiet file-output mode.

## Scope Control

No R005-R009 remediation was performed. R009 remains open because total project
coverage is still 79%, below the 85% gate. Week 7 remains blocked by Stage 2
items even though R011 is now complete.
