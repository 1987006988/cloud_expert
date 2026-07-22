# PostgreSQL Validation

PostgreSQL remains the target database. Stage 1 originally blocked on Docker
daemon access, and that blocked evidence is preserved under
`reports/remediation/r011/`.

R011 live validation was completed in a second, separate run:

`reports/remediation/r011/runs/run_02/`

## Run 02 Verdict

`R011_STATUS=COMPLETED`

`WEEK7_GATE=NO-GO`

Week 7 remains gated because R005-R009 are still open.

## Environment

| Field | Value |
| --- | --- |
| Docker client/server | `25.0.3` |
| Docker Compose | `v2.24.6-desktop.1` |
| PostgreSQL image | `postgres:16` |
| PostgreSQL server | `PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1)` |
| Container | `cloud_expert-postgres-1` |
| Container state | `running`, `healthy` |
| Port | `54329 -> 5432` |
| Timezone | `Etc/UTC` |

## Databases

R011 used isolated PostgreSQL databases:

- `cloud_expert_r011_fresh`
- `cloud_expert_r011_full`
- `cloud_expert_r011_tests`

No SQLite result was used as a substitute.

## Migration Results

Passing commands:

```powershell
.\.venv312\Scripts\python.exe -m alembic -x database_url=<fresh> upgrade head
.\.venv312\Scripts\python.exe -m alembic -x database_url=<fresh> downgrade -1
.\.venv312\Scripts\python.exe -m alembic -x database_url=<fresh> upgrade head
.\.venv312\Scripts\python.exe -m alembic -x database_url=<full> upgrade head
.\.venv312\Scripts\python.exe -m alembic -x database_url=<full> downgrade base
.\.venv312\Scripts\python.exe -m alembic -x database_url=<full> upgrade head
```

Schema fingerprints matched after excluding only the database URL:

- `schema_after_first_upgrade.json`
- `schema_after_reupgrade.json`

## PostgreSQL Compatibility Fix

PostgreSQL exposed an Alembic compatibility issue: the default
`alembic_version.version_num VARCHAR(32)` is too short for existing revision
IDs such as `0006_week06_canonical_normalization`.

Migration `0004_week04_aws_partition_availability` now widens
`alembic_version.version_num` to `VARCHAR(128)` for PostgreSQL before the first
long revision ID is written.

## Test Results

| Command | Result |
| --- | --- |
| `pytest -m postgres -ra` | 6 passed |
| `pytest tests\integration -m "not network" -ra` | 6 passed |
| `pytest -m "not network" -ra` | 71 passed |
| coverage run | 71 passed, 79% total coverage |
| `ruff format .` | passed |
| `ruff format --check .` | passed |
| `ruff check .` | passed |
| `mypy src scripts` | passed, 172 source files |

PostgreSQL-specific tests cover enum-like check constraints, Numeric/Decimal
precision, JSON behavior, foreign keys, unique constraints, timezone,
transaction rollback, and concurrent unique-conflict behavior.

## Remaining Non-R011 Risks

- R005 Canonical schema expansion remains open.
- R006 Field Matrix required columns remain open.
- R007 ComparabilityAssessment strengthening remains open.
- R008 ReviewItem governance remains open.
- R009 coverage uplift remains open because total coverage is still 79%.

R011 is closed, but Week 7 product mapping must not start until Stage 2 is
closed or explicitly waived.
