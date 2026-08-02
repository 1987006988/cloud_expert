# Project State

## Current Phase

Remediation Stage 1 core recovery, R011 live PostgreSQL validation, Stage 2
engineering remediation for R005, R006, R007, and R009, Week 7 mapping, Week 8
evidence packages, Week 9 pricing/TCO readiness, and Week 10 internal decision
engine delivery are complete in the local workspace. The project now has a Git
delivery baseline, a rebuilt default SQLite database at current Alembic head, a
restored Week 6 evidence chain, live PostgreSQL migration and integration
validation, expanded canonical governance metadata, blocker-aware comparability
assessment, regenerated field matrices, 85% test coverage, versioned pricing
and TCO records, and internal-only scenario decision candidates.

The stable Stage 1 recovery checkpoint is commit `fa75ded`; R011 live validation
is recorded under `reports/remediation/r011/runs/run_02/`.

`WEEK7_GATE=GO`
`WEEK8_GATE=GO`
`WEEK9_GATE=GO`
`WEEK10_GATE=GO`

R008 was waived by the project owner for internal engineering execution. Review
files remain available under `D:\审核文件`, but waived/pending-review facts are
not customer eligible.

Current data model version:

- Alembic revision: `0010_week10_decision_engine`
- Application tables: 52
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
- Stage 2 expanded canonical field metadata in `metadata_json` with semantic
  group, evidence requirement, review policy, lifecycle/deprecation fields, and
  comparability tier/status.
- Stage 2 regenerated field matrices with semantic, unit, qualifier, scope,
  evidence, comparability, lifecycle, and review-policy status columns.
- Stage 2 strengthened comparability assessment to block on pending-review
  normalized values, unit set mismatch, qualifier mismatch, scope mismatch, and
  market-scope differences.
- Stage 2 exported all human-review material to `D:\审核文件`.
- Stage 2 raised total coverage to 85%.
- Week 7 generated internal cross-vendor mapping candidates and evidence links
  without creating approved/customer-facing mappings.
- Week 8 generated internal evidence packages with customer eligibility set to
  false for all packages.
- Week 9 registered Huawei Cloud ECS/OBS official pricing sources, completed
  pricing source terms and collection-mode audit across Huawei Cloud, AWS, and
  Aliyun, captured immutable pricing snapshots, and generated internal
  PriceSKU, PriceSnapshot, CostLineItem, and TCOResult records.
- Week 10 added versioned decision scenarios, scenario requirements, scoring
  policies, scoring rules, hard-block evaluation, Business Fit, Confidence,
  Completeness, sensitivity status, internal reporting, and review workflow
  placeholders.
- Week 10 seeded 5 standard scenarios and 5 scoring policies, then generated 5
  internal decision runs with 1,230 machine-generated candidate results. All
  decision results remain `internal_only`; customer-eligible decision
  candidates: 0.

## Week 9 Pricing/TCO Metrics

| Metric | Count |
| --- | ---: |
| Pricing registry sources | 10 |
| Automated pricing sources | 8 |
| Manual/browser pricing sources | 2 |
| Pricing SourceDocuments | 12 |
| Pricing Evidence records | 13 |
| PriceSKU rows | 1 |
| PriceSnapshot rows | 1 |
| TCO line items | 6 |
| TCO results | 6 |

Current structured price coverage is deliberately narrow: AWS S3 Standard
storage in `us-east-1` is the only persisted list price because it is backed by
the official AWS Price List Bulk API snapshot. Huawei Cloud ECS/OBS, AWS EC2,
Aliyun ECS, and Aliyun OSS TCO dimensions remain explicit `missing_price` items
until official snapshots with product, region, unit, currency, and numeric price
are captured.

## Week 10 Decision Metrics

| Metric | Count |
| --- | ---: |
| Decision scenarios | 5 |
| Scoring policies | 5 |
| Decision runs | 5 |
| Candidate decision results | 1,230 |
| Machine-generated results | 1,230 |
| Internal-only results | 1,230 |
| Customer-eligible results | 0 |
| Formal ranked candidates | 0 |

The absence of formal ranked candidates is intentional: current mappings and
evidence packages remain pending review, and most TCO inputs are incomplete.

Latest broad coverage run after Week 10 reports 70% because Week 9/Week 10
orchestration modules are now included in coverage but are not yet fully
unit-tested. Functional Gate, evidence, idempotency, lint, mypy, migration, and
PostgreSQL checks passed; coverage hardening remains a follow-up before broader
release claims.

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
| Pending-review normalized rows | 678 |
| Scope mismatch warnings | 0 |
| Comparability assessments | 116 |
| Comparable assessments | 13 |
| Partial assessments | 64 |
| Not-comparable assessments | 37 |
| Needs-review assessments | 2 |
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

Latest Stage 2 checks executed on Python 3.12.13 from `.venv312`.

| Command | Result |
| --- | --- |
| `ruff format .` | passed |
| `ruff check .` | passed |
| `mypy src scripts` | passed, 173 source files |
| `pytest -m "not network" --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports/remediation/stage2/coverage.json` | passed, 83 passed / 6 skipped, 85% coverage |
| `scripts/validate_source_registry.py` | passed, 74 valid sources / 4 disabled / 0 errors |
| `scripts/validate_raw_snapshots.py` | passed, 90 snapshots checked / 0 errors |
| `scripts/validate_canonical_definitions.py` | passed, 38 canonical fields / 40 mappings / 0 errors |
| `scripts/validate_canonical_units.py` | passed, 10172 checked / 0 errors |
| `scripts/validate_value_qualifiers.py` | passed, no unknown qualifiers |
| `scripts/validate_normalized_evidence.py` | passed, 10172 normalized rows / 0 missing links / 0 hash mismatches |
| `scripts/validate_week06_projection.py` | passed, all required entities present and product samples valid |
| `scripts/validate_default_database.py` | passed, default SQLite at `0009_week09_pricing_tco` |
| `alembic current` with default settings | passed after Week 9 migration, `0009_week09_pricing_tco (head)` |
| `docker compose config` | passed |
| PostgreSQL live migration validation | passed, R011 run_02 |
| `pytest -m postgres -ra` | passed, 6 PostgreSQL tests |
| `scripts/run_week09_pricing_pipeline.py --force-fetch` | passed, 8 automated price sources fetched |
| `scripts/validate_pricing_sources.py` | passed, 10 sources / 0 missing / 0 terms errors |
| `scripts/validate_price_skus.py` | passed, 1 PriceSKU / 1 PriceSnapshot |
| `scripts/validate_price_evidence.py` | passed, 100% price evidence completeness |
| `scripts/check_price_freshness.py` | passed, 1 current price snapshot |
| `scripts/validate_cost_calculation_idempotency.py` | passed, 6 line items / missing prices not zero |

## Acceptance Databases

- Week 3 Huawei acceptance: `test_outputs/week3_huawei_acceptance.sqlite`
- Week 4 AWS acceptance: `test_outputs/week4_aws_acceptance.sqlite`
- Week 5 Aliyun acceptance: `test_outputs/week5_aliyun_acceptance_v2.sqlite`
- Week 6 combined projection:
  `test_outputs/week6_combined_projection.sqlite`

## Known Issues

- Human review is waived for internal engineering only. Pending-review and
  waived facts are not customer eligible.
- 240 input specifications could not be normalized into exactly one canonical
  value.
- Huawei Cloud Week 3 acceptance still has no normalized Region rows.
- Comparability assessments are readiness records only and must not be used as
  sales claims, competitive conclusions, product mappings, or pricing guidance.
- Week 9 TCO is partial: five provider/product dimensions have no official
  PriceSnapshot and remain excluded from totals.

## Next Step Recommendation

Continue by adding approved official concrete price snapshots for Huawei Cloud
ECS/OBS, AWS EC2, and Aliyun ECS/OSS before using TCO beyond internal readiness
checks. RAG, frontend, LLM calls, competitive scoring, and sales scripts remain
out of scope until explicitly approved.
