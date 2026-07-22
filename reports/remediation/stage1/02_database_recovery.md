# Database Recovery

The default `cloud_expert_dev.sqlite` was backed up and rebuilt.

Backup manifest:

`backups/remediation_stage1/cloud_expert_dev_backup_manifest.json`

Old database revision:

`0002_ingestion_runs_and_snapshots`

Recovered default database:

```text
alembic current
0006_week06_canonical_normalization (head)
```

`scripts/validate_default_database.py` returned:

```json
{
  "head": "0006_week06_canonical_normalization",
  "alembic_versions": ["0006_week06_canonical_normalization"],
  "missing_required_tables": [],
  "stale_revisions": [],
  "valid": true
}
```

Schema inspection is stored in `default_schema.json`.
