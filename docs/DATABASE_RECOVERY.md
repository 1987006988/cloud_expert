# Database Recovery

Stage 1 fixed the default local database path and rebuilt the stale default
SQLite database without manually editing Alembic bookkeeping.

## Root Cause

The previous `cloud_expert_dev.sqlite` contained:

- `alembic_version = 0002_ingestion_runs_and_snapshots`
- no matching migration file for that revision name
- no `Evidence` rows
- no `ProductSpecification` rows

That made default `alembic current` fail even though fresh databases could
upgrade to the current head.

## Backup

The stale local database was copied before replacement.

- Backup manifest:
  `backups/remediation_stage1/cloud_expert_dev_backup_manifest.json`
- Backup SHA-256:
  `3802a179db684d1c58e21c37f9ac3e107af649c3c8761c08e21fece99c080a61`
- Backup data value: stale development database with no product specifications
  and no evidence rows
- Backup SQLite file is intentionally ignored by Git.

## Recovery Action

The stale default database was removed after backup and recreated with:

```powershell
.\.venv312\Scripts\python.exe -m alembic upgrade head
```

The default SQLite URL is now resolved relative to the project root, not the
current shell directory.

## Validation

Passing checks on 2026-07-22:

```text
alembic current
0006_week06_canonical_normalization (head)

alembic heads
0006_week06_canonical_normalization (head)

scripts/validate_default_database.py
valid: true
alembic_versions: ["0006_week06_canonical_normalization"]
missing_required_tables: []
stale_revisions: []
```

Schema inspection output is stored at:

`reports/remediation/stage1/default_schema.json`
