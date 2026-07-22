# Project State

## Current Phase

Remediation Stage 1 core recovery is complete after the Week 1-6 independent
audit and R011 follow-up. The project now has a Git delivery baseline, a
rebuilt default SQLite database at current Alembic head, a restored Week 6
evidence chain, Stage 1 validation reports, and live PostgreSQL migration and
integration validation. The stable Stage 1 recovery checkpoint is commit
`fa75ded`; R011 live validation is recorded under
`reports/remediation/r011/runs/run_02/`.

`WEEK7_GATE=NO-GO`

Current data model version:

- Alembic revision: `0006_week06_canonical_normalization`
- Application tables: 34
- Target database: PostgreSQL
- Fast unit/migration substitute: SQLite, used only for tests and acceptance
  projections

## Completed Items

- Week 1 product data model and database foundation remain in place.
- Week 2 source registry, safe fetcher, raw snapshot storage, change detection,
  and ingestion audit layer remain in place.
- Week 3 Huawei Cloud domestic ECS/OBS parsing, evidence, review, quality
  reports, and documentation remain in place.
- Week 4 AWS commercial global EC2/S3 parsing, partition support, product-level
  Region availability, reports, and documentation remain in place.
- Week 5 Aliyun domestic ECS/OSS parsing, `aliyun_public_cn` partition support,
  Zone availability, reports, and documentation remain in place.
- Added canonical normalization enums and tables:
  `canonical_field_definition`, `normalization_rule`, `normalization_run`,
  `normalized_specification`, and `comparability_assessment`.
- Added 38 canonical field definitions and 40 legacy field mappings.
- Added unit standardization for count, GiB, KiB, Gbps, PPS, IOPS, percent, and
  day values.
- Added field-level comparability-readiness assessment limited to matching
  domains: ECS/EC2 compute and OBS/S3/OSS object storage.
- Generated normalization reports under `reports/normalization/`.
- Built `test_outputs/week6_combined_projection.sqlite` from upgraded copies of
  Week 3, Week 4, and Week 5 acceptance databases.
- Stage 1 established Git baseline commit `65ab21a` on `main`, remote
  `git@github.com:1987006988/cloud_expert.git`, and baseline tags
  `audit-week01-06-baseline` and `audit-week06-baseline`.
- Stage 1 rebuilt default `cloud_expert_dev.sqlite` to Alembic head
  `0006_week06_canonical_normalization`.
- Stage 1 rebuilt the Week 6 projection with `SnapshotRecord`, `IngestionRun`,
  `ParsingRun`, `ParsedFieldCandidate`, product shape, SLA, partition, region,
  availability, and review rows preserved.
- Stage 1 reports are stored under `reports/remediation/stage1/`.
- R011 live PostgreSQL validation completed with Docker Desktop PostgreSQL
  16.14, fresh upgrade, downgrade `-1`, re-upgrade, downgrade base, re-upgrade
  from base, matching schema fingerprints, and 6 PostgreSQL integration tests.

## Week 6 Acceptance Metrics

| Metric | Count |
| --- | ---: |
| Source documents projected | 67 |
| Evidence records projected | 14113 |
| Product specifications projected | 10412 |
| Canonical field definitions | 38 |
| Normalization rules | 40 |
| Normalized specifications | 10172 |
| Skipped specifications | 240 |
| Pending-review normalized rows | 768 |
| Scope mismatch warnings | 90 |
| Comparability assessments | 116 |
| Comparable assessments | 13 |
| Partial assessments | 66 |
| Not-comparable assessments | 37 |
| Missing normalized evidence links | 0 |

Product normalized specification counts:

| Product | Rows |
| --- | ---: |
| `aliyun/ecs` | 6281 |
| `aliyun/oss` | 30 |
| `aws/ec2` | 3616 |
| `aws/s3` | 17 |
| `huawei_cloud/ecs` | 185 |
| `huawei_cloud/obs` | 43 |

## Test Status

Latest Stage 1 checks executed on Python 3.12.13 from `.venv312`.

| Command | Result |
| --- | --- |
| `ruff format .` | passed |
| `ruff check .` | passed |
| `mypy src scripts` | passed, 172 source files |
| `pytest --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports/remediation/r011/runs/run_02/coverage.json` | passed, 71 passed / 0 failed, 79% coverage |
| `scripts/validate_source_registry.py` | passed, 74 valid sources / 4 disabled / 0 errors |
| `scripts/validate_raw_snapshots.py` | passed, 90 snapshots checked / 0 errors |
| `scripts/validate_canonical_definitions.py` | passed, 38 canonical fields / 40 mappings / 0 errors |
| `scripts/validate_canonical_units.py` | passed, 10172 checked / 0 errors |
| `scripts/validate_value_qualifiers.py` | passed, no unknown qualifiers |
| `scripts/validate_normalized_evidence.py` | passed, 10172 normalized rows / 0 missing links / 0 hash mismatches |
| `scripts/validate_week06_projection.py` | passed, all required entities present and product samples valid |
| `scripts/validate_default_database.py` | passed, default SQLite at `0006_week06_canonical_normalization` |
| `alembic current` with default settings | passed, `0006_week06_canonical_normalization (head)` |
| `docker compose config` | passed |
| PostgreSQL live migration validation | passed, R011 run_02 |
| `pytest -m postgres -ra` | passed, 6 PostgreSQL tests |

## Acceptance Databases

- Week 3 Huawei acceptance: `test_outputs/week3_huawei_acceptance.sqlite`
- Week 4 AWS acceptance: `test_outputs/week4_aws_acceptance.sqlite`
- Week 5 Aliyun acceptance: `test_outputs/week5_aliyun_acceptance_v2.sqlite`
- Week 6 combined projection:
  `test_outputs/week6_combined_projection.sqlite`

## Known Issues

- Overall test coverage is 79%, below the 85% remediation backlog target.
- Human review is not complete. Prior low-confidence queues remain open.
- 240 input specifications could not be normalized into exactly one canonical
  value.
- 90 object-storage rows are evidence-backed but product-scoped because prior
  normalized specifications do not store a service-tier key.
- Huawei Cloud Week 3 acceptance still has no normalized Region rows.
- Comparability assessments are readiness records only and must not be used as
  sales claims, competitive conclusions, product mappings, or pricing guidance.

## Next Step Recommendation

Do not start Week 7 product mapping yet. R011 is closed, but Remediation Stage
2 is still required for Canonical schema/enums, qualifier and scope rules,
ComparabilityAssessment, Field Matrix status columns, coverage uplift, and
ReviewItem governance.
Pricing/TCO, RAG, frontend, LLM calls, competitive scoring, and sales scripts
remain out of scope until explicitly approved.
