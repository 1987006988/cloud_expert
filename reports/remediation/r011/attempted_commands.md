# Attempted Commands

Generated at: 2026-07-22T22:43:55+08:00

This file records the real precheck commands executed before R011 was blocked.
Secrets are redacted where command output rendered local test credentials.

## Git

```text
$ git status
exit_code=0
On branch main
Your branch is ahead of 'origin/main' by 2 commits.
nothing to commit, working tree clean
```

```text
$ git branch --show-current
exit_code=0
main
```

```text
$ git log --oneline --decorate --graph -20
exit_code=0
* 998af5c (HEAD -> main) docs(remediation): mark stage1 partial and week7 no-go
* fa75ded fix(remediation): recover stage1 database and evidence baseline
* 65ab21a (tag: audit-week06-baseline, tag: audit-week01-06-baseline, origin/main) chore: baseline week01-06 audit
```

```text
$ git tag --list
exit_code=0
audit-week01-06-baseline
audit-week06-baseline
```

```text
$ git remote -v
exit_code=0
origin git@github.com:1987006988/cloud_expert.git (fetch)
origin git@github.com:1987006988/cloud_expert.git (push)
```

## Docker

```text
$ docker version
exit_code=1
Client Version: 25.0.3
Context: default
error during connect: this error may indicate that the docker daemon is not running:
open //./pipe/docker_engine: The system cannot find the file specified.
```

```text
$ docker info
exit_code=1
Client Version: 25.0.3
Context: default
Server:
ERROR: error during connect: this error may indicate that the docker daemon is not running:
open //./pipe/docker_engine: The system cannot find the file specified.
```

```text
$ docker compose version
exit_code=0
Docker Compose version v2.24.6-desktop.1
```

```text
$ docker compose config
exit_code=0
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: cloud_expert_test
      POSTGRES_USER: cloud_expert
      POSTGRES_PASSWORD: <redacted>
    ports:
      - published: "54329"
        target: 5432
    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -U cloud_expert -d cloud_expert_test
      interval: 5s
      timeout: 3s
      retries: 10
```

```text
$ docker compose ps
exit_code=1
error during connect: this error may indicate that the docker daemon is not running:
open //./pipe/docker_engine: The system cannot find the file specified.
```

## Alembic

```text
$ .\.venv312\Scripts\python.exe -m alembic heads
exit_code=0
0006_week06_canonical_normalization (head)
```

```text
$ .\.venv312\Scripts\python.exe -m alembic history
exit_code=0
0005_week05_aliyun_zone_availability -> 0006_week06_canonical_normalization (head)
0004_week04_aws_partition_availability -> 0005_week05_aliyun_zone_availability
0003_week03_parsing_models -> 0004_week04_aws_partition_availability
0002_ingestion_snapshots -> 0003_week03_parsing_models
0001_initial_product_data_model -> 0002_ingestion_snapshots
<base> -> 0001_initial_product_data_model
```

## PostgreSQL Configuration Search

```text
$ rg -n "postgres" docker-compose.yml .env.example alembic.ini src tests
exit_code=0
.env.example:3:POSTGRES_DATABASE_URL=postgresql+psycopg://cloud_expert:<redacted>@localhost:54329/cloud_expert_test
docker-compose.yml:2:  postgres:
docker-compose.yml:3:    image: postgres:16
```

```text
$ rg -n "DATABASE_URL" .env.example docker-compose.yml alembic.ini src tests
exit_code=0
.env.example:2:DATABASE_URL=sqlite:///./cloud_expert_dev.sqlite
.env.example:3:POSTGRES_DATABASE_URL=postgresql+psycopg://cloud_expert:<redacted>@localhost:54329/cloud_expert_test
.env.example:4:TEST_DATABASE_URL=sqlite:///:memory:
tests\unit\test_additional_schemas_and_config.py:26:    monkeypatch.setenv("DATABASE_URL", "sqlite:///./synthetic_settings.sqlite")
src\cloud_expert\config\settings.py:52:        database_url=resolve_database_url(os.getenv("DATABASE_URL")),
```

## Integration Test Directory

```text
$ Test-Path tests\integration
exit_code=0
True
```

```text
$ Get-ChildItem -Force tests\integration
exit_code=0
<no files>
```
