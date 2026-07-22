# SQLite And PostgreSQL Differences

Generated at: 2026-07-22T23:02:12+08:00

| Area | Status | R011 Finding |
| --- | --- | --- |
| Enum-like values | Acceptable difference | PostgreSQL uses real check constraints. SQLite tests also define checks, but PostgreSQL enforcement was separately validated. No native PostgreSQL enum types exist. |
| JSON vs JSONB | Acceptable difference | Models use SQLAlchemy `JSON`; PostgreSQL columns are `JSON`, not `JSONB`. No JSONB behavior is claimed. |
| Numeric precision | Confirmed difference | PostgreSQL enforces `NUMERIC(24,8)` and returns `Decimal`; SQLite is looser. PostgreSQL rounding was validated. |
| Boolean | Acceptable difference | PostgreSQL has native boolean; SQLite stores booleans differently. Existing ORM usage works in PostgreSQL tests. |
| DateTime/timezone | Confirmed risk | PostgreSQL server timezone is `Etc/UTC`; timezone-aware writes/readbacks were validated. SQLite cannot prove this behavior. |
| Foreign keys | Confirmed difference | PostgreSQL enforces FKs by default. SQLite requires PRAGMA in tests. PostgreSQL FK rejection was validated. |
| Unique constraints | No blocking difference | PostgreSQL unique constraints reject duplicates and concurrency races as expected. |
| Case sensitivity | Not blocking | No R011-specific blocker found. Future text-search or identifier policy should remain explicit. |
| Null sorting | Not tested | No R011 query depends on null sort order. Record as future query portability concern. |
| Partial indexes | Not applicable | Current inspected schema does not depend on PostgreSQL partial indexes. |
| Concurrency | Confirmed difference | PostgreSQL provides real concurrent transaction behavior; SQLite cannot substitute for this. R011 concurrent duplicate insert was validated. |
| Transactions | Confirmed difference | PostgreSQL transactional rollback was validated with multi-row chain rollback. |
| DDL rollback | Confirmed | PostgreSQL transactional Alembic DDL succeeded through upgrade, downgrade, and re-upgrade. |
| Alembic behavior | Fixed | PostgreSQL exposed Alembic `version_num VARCHAR(32)` incompatibility with long revision IDs; migration `0004` now widens it to `VARCHAR(128)`. |

## Conclusion

SQLite remains acceptable for fast unit and fixture tests, but cannot replace
PostgreSQL for R011. R011 now has live PostgreSQL coverage for migration,
constraints, numeric precision, timezone, transaction, and concurrency behavior.
