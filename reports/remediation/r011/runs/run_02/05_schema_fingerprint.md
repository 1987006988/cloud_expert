# Schema Fingerprint

Generated at: 2026-07-22T23:02:12+08:00

## Files

- `reports/remediation/r011/runs/run_02/schema_after_first_upgrade.json`
- `reports/remediation/r011/runs/run_02/schema_after_reupgrade.json`

## Comparison

The two schema fingerprints were compared after removing only
`database_url`, because the fingerprints were generated from different
isolated databases.

```text
schema_equal_ignoring_database_url = True
tables_first = 35
tables_reupgrade = 35
head_first = ["0006_week06_canonical_normalization"]
head_reupgrade = ["0006_week06_canonical_normalization"]
postgres_enums_first = 0
postgres_enums_reupgrade = 0
```

## Coverage

The fingerprint includes:

- tables
- columns
- column types
- nullability
- defaults
- primary keys
- foreign keys
- unique constraints
- check constraints
- indexes
- PostgreSQL native enum inventory

## Conclusion

`SCHEMA_FINGERPRINT_MATCH=PASSED`

Fresh upgrade and downgrade-base re-upgrade produce the same PostgreSQL schema.
