# Database Audit

## Verdict

**PARTIAL.** SQLite migration chains are healthy on fresh/prior-week audit databases, but default DB and PostgreSQL verification fail or are not verifiable.

## Passed

- `alembic history`: linear chain from `0001` to `0006`.
- `alembic heads`: single head `0006_week06_canonical_normalization`.
- Fresh audit SQLite DB: `upgrade head`, `downgrade -1`, and `upgrade head` all passed.
- Copies of Week3, Week4, and Week5 acceptance DBs upgraded to head successfully.

## Failed

- Default `cloud_expert_dev.sqlite` cannot run `alembic current`: missing revision `0002_ingestion_runs_and_snapshots`.
- Default `validate_evidence_links.py` fails because the default DB lacks current tables.

## Not Verifiable

- PostgreSQL migration behavior. Docker CLI exists, but Docker daemon was not running during audit.
