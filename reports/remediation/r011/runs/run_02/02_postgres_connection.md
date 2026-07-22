# PostgreSQL Connection Validation

Generated at: 2026-07-22T23:02:12+08:00

## Command

```powershell
.\.venv312\Scripts\python.exe scripts\check_database_connection.py --database-url <redacted R011 fresh URL>
```

## Result

`SQLALCHEMY_CONNECTION=PASSED`

The script connected through SQLAlchemy using the project runtime dependency
stack and validated:

- `SELECT 1`
- PostgreSQL server version
- current database
- current user
- current schema
- current timezone
- connection pool initialization
- transaction commit
- transaction rollback

## Observed Identity

| Field | Value |
| --- | --- |
| Database URL | `postgresql+psycopg://cloud_expert:***@localhost:54329/cloud_expert_r011_fresh` |
| Dialect | `postgresql` |
| Server | `PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1)` |
| Current database | `cloud_expert_r011_fresh` |
| Current user | `cloud_expert` |
| Current schema | `public` |
| Timezone | `Etc/UTC` |
| `SELECT 1` | passed |
| Transaction commit | passed |
| Transaction rollback | passed |

No database password was printed by the script or recorded in this report.
