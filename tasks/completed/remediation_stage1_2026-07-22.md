# Completed Subtasks: Remediation Stage 1 Stable Checkpoint

Date: 2026-07-22

Stage verdict: **partial complete**.

`WEEK7_GATE=NO-GO`

Completed:

- Git delivery baseline documented.
- Default SQLite database backed up and rebuilt to Alembic head.
- Week 6 combined projection rebuilt with snapshot, ingestion, parsing, review,
  product shape, SLA, partition, region, and availability entities.
- Normalized evidence chain validated through raw files and manifests.
- Stage 1 reports written under `reports/remediation/stage1/`.
- Quality gates passed except PostgreSQL live validation and the 85% coverage
  threshold.

R011 follow-up:

- Live PostgreSQL validation completed in
  `reports/remediation/r011/runs/run_02/`.
- PostgreSQL 16.14 container was healthy.
- Fresh upgrade, downgrade `-1`, re-upgrade, downgrade base, and re-upgrade
  from base passed.
- PostgreSQL integration tests passed: 6/6.

Remaining:

- Coverage uplift to 85% or a project-approved coverage gate.
- Later-stage canonical schema, matrix, comparability, and review queue work.
