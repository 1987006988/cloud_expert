# Project State

## Current Phase

Week 6 is complete for the scoped engineering slice: cross-provider canonical
field definitions, legacy field mapping rules, unit normalization, qualifier and
scope preparation, combined acceptance projection, normalized specification
rows, field-level comparability-readiness assessments, validation scripts,
reports, tests, and documentation.

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

Executed on Python 3.12.13 from `.venv312`.

| Command | Result |
| --- | --- |
| `ruff check .` | passed |
| `mypy src` | passed, 138 source files |
| `pytest -m "not network"` | passed, 62 passed / 0 failed |
| `scripts/validate_source_registry.py` | passed, 74 valid sources / 4 disabled / 0 errors |
| `scripts/validate_raw_snapshots.py` | passed, 90 snapshots checked / 0 errors |
| `scripts/validate_canonical_definitions.py` | passed, 38 canonical fields / 40 mappings / 0 errors |
| `scripts/validate_canonical_units.py` | passed, 10172 checked / 0 errors |
| `scripts/validate_value_qualifiers.py` | passed, no unknown qualifiers |
| `scripts/validate_normalized_evidence.py` | passed, 0 missing normalized evidence links |
| `alembic upgrade head` on fresh SQLite | passed, upgraded to `0006_week06_canonical_normalization` |

## Acceptance Databases

- Week 3 Huawei acceptance: `test_outputs/week3_huawei_acceptance.sqlite`
- Week 4 AWS acceptance: `test_outputs/week4_aws_acceptance.sqlite`
- Week 5 Aliyun acceptance: `test_outputs/week5_aliyun_acceptance_v2.sqlite`
- Week 6 combined projection:
  `test_outputs/week6_combined_projection.sqlite`

## Known Issues

- The repository still has no Git commits, so `git log` reports that the
  current branch has no commits.
- The default local `cloud_expert_dev.sqlite` is older than current migrations;
  fresh databases upgrade cleanly.
- Human review is not complete. Prior low-confidence queues remain open.
- 240 input specifications could not be normalized into exactly one canonical
  value.
- 90 object-storage rows are evidence-backed but product-scoped because prior
  normalized specifications do not store a service-tier key.
- Huawei Cloud Week 3 acceptance still has no normalized Region rows.
- Comparability assessments are readiness records only and must not be used as
  sales claims, competitive conclusions, product mappings, or pricing guidance.

## Next Week Recommendation

Week 7 should either resolve human review queues and service-tier scope gaps, or
design a reviewed product-mapping policy. Pricing/TCO, RAG, frontend, LLM calls,
competitive scoring, and sales scripts should remain out of scope until
explicitly approved.
