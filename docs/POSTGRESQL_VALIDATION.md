# PostgreSQL Validation

PostgreSQL remains the target database. Stage 1 attempted to run the
PostgreSQL validation path, but the local Docker daemon was unavailable.

## What Passed

Configuration rendering passed:

```powershell
docker compose config
```

The rendered service uses:

- image: `postgres:16`
- database: `cloud_expert_test`
- user: `cloud_expert`
- published port: `54329`

## What Was Blocked

The command:

```powershell
docker compose up -d postgres
```

failed with:

```text
open //./pipe/docker_engine: The system cannot find the file specified
```

`docker version` showed the Docker client but failed to connect to the server
with the same missing Windows pipe. Therefore the migration scripts were not
validated against a live PostgreSQL server in Stage 1.

## Required Follow-Up

When Docker Desktop or another Docker daemon is running:

```powershell
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+psycopg://cloud_expert:cloud_expert_password@localhost:54329/cloud_expert_test"
.\.venv312\Scripts\python.exe -m alembic upgrade head
.\.venv312\Scripts\python.exe -m alembic downgrade base
.\.venv312\Scripts\python.exe -m alembic upgrade head
```

Stage 1 closeout requires this sequence before Week 7 can be reconsidered:

```text
start Docker Desktop
start PostgreSQL container
fresh migration
downgrade -1
upgrade head
PostgreSQL integration tests
check enum, numeric, foreign key, unique constraint, and timezone behavior
```

Backlog item `R011_postgresql_migration_validation` remains open until those
commands run successfully against a live PostgreSQL instance.
