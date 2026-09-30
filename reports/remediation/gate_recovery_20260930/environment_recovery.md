# Local Verification Environment Recovery

Observed on 2026-09-30. This is an execution note, not a Gate approval.

- Docker Desktop initially failed at a stale temporary socket in its local `run`
  directory. With all Docker processes stopped, the verified temporary directory
  was renamed to `run.blocked-20260930`; it was not deleted. No Docker volume or
  business database was removed. Docker Desktop then started successfully.
- An isolated `postgres:16` container was created with a loopback-only port
  mapping at `127.0.0.1:54329`. Image digest:
  `sha256:1a6ab3f5345eb6dbe04a1349529caabdb0ab09293a09590fad07b2246bfa4b54`.
- `pg_isready` succeeded. A direct read-only IPv4 connection returned PostgreSQL
  16.15. Test connection credentials are not recorded in this note.
- The first quarantine integration preflight used `localhost` and did not
  complete. Its two verified test Python processes were stopped. No passing
  result is claimed for that attempt.
- The second preflight reached PostgreSQL but failed before test bodies because
  its pytest temporary directory's parent was absent. Its JUnit is preserved.
- The third preflight created a separate report parent and used IPv4. All four
  real PostgreSQL quarantine tests passed in 10.39 seconds. See
  `postgres_quarantine_preflight_03/junit.xml`.
- A data-free `gpt-6-astra` CLI availability probe succeeded. This is not a
  Decision review. See `model_probe_01.json`.

These preflights do not replace the frozen-code migration and regression receipts.
