# cloud-competitive-expert

Evidence-first data foundation for a Huawei Cloud competitive sales expert.

Week 1 implements the product data model, database migration baseline, Pydantic
contracts, repositories, synthetic fixtures, and tests.

Week 2 adds the official source registry foundation, immutable raw snapshot
storage, ingestion run auditing, lightweight content inspection, and change
detection. The repository still does not extract real cloud product facts, call
pricing APIs, run LLMs, or generate sales recommendations.

Week 3 adds Huawei Cloud domestic ECS/OBS official source ingestion and
snapshot-backed parsing.

Week 4 adds AWS commercial global EC2/S3 official source ingestion,
snapshot-backed parsing, cloud partition modeling, product-level Region
availability, quality reports, and manual review samples. Pricing, TCO,
competitive mapping, LLM/RAG, frontend, and sales scripts remain out of scope.

Week 5 adds Aliyun domestic China public cloud ECS/OSS official source
ingestion, snapshot-backed parsing, product-level Region/Zone availability,
quality reports, and manual review samples under
`cloud_partition=aliyun_public_cn`. Pricing, mapping, LLM/RAG, frontend, and
sales scripts remain out of scope.

Week 6 adds a derived canonical normalization layer with cross-provider field
definitions, unit standardization, value qualifiers, scope preparation,
field-level comparability-readiness assessments, and normalization reports.
It does not create product mappings, pricing/TCO, competitive scoring, or
sales claims.

Remediation Stage 1 establishes the Git delivery baseline, rebuilds the default
SQLite database to current Alembic head, restores the Week 6 evidence chain,
and records validation reports under `reports/remediation/stage1/`.
It is a partial-complete checkpoint; `WEEK7_GATE=NO-GO` until PostgreSQL live
validation, coverage, and Stage 2 governance items are closed or explicitly
waived.

## Local Setup

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

For PostgreSQL migration checks:

```bash
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+psycopg://cloud_expert:cloud_expert_password@localhost:54329/cloud_expert_test"
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

## Quality Gates

```bash
ruff format .
ruff check .
mypy src
pytest
pytest --cov=src/cloud_expert --cov-report=term-missing
```

Stage 1 uses:

```bash
ruff format .
ruff check .
mypy src scripts
pytest --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports/remediation/stage1/coverage.json
.\.venv312\Scripts\python scripts\validate_default_database.py
.\.venv312\Scripts\python scripts\validate_week06_projection.py
```

## Week 2 Source Commands

```bash
.\.venv312\Scripts\python scripts\validate_source_registry.py
.\.venv312\Scripts\python scripts\ingest_source.py --source-id synthetic_html_fixture
.\.venv312\Scripts\python scripts\show_source_history.py --source-id synthetic_html_fixture
.\.venv312\Scripts\python scripts\compare_source_versions.py --source-id synthetic_html_fixture --latest
.\.venv312\Scripts\python scripts\validate_raw_snapshots.py
```

The included registry entries are synthetic `.invalid` fixtures only.

## Week 4 AWS Commands

```bash
.\.venv312\Scripts\python scripts\validate_source_registry.py --provider aws
.\.venv312\Scripts\python scripts\ingest_source.py --provider aws --enabled-only --dry-run
.\.venv312\Scripts\python scripts\ingest_source.py --provider aws --enabled-only --force
.\.venv312\Scripts\python scripts\parse_product_sources.py --provider aws
.\.venv312\Scripts\python scripts\generate_data_quality_report.py --provider aws --product ec2
.\.venv312\Scripts\python scripts\generate_data_quality_report.py --provider aws --product s3
.\.venv312\Scripts\python scripts\validate_provider_partitions.py --provider aws --partition aws
.\.venv312\Scripts\python scripts\generate_manual_review_sample.py --provider aws
```

## Week 5 Aliyun Commands

```bash
.\.venv312\Scripts\python scripts\validate_source_registry.py --provider aliyun
.\.venv312\Scripts\python scripts\ingest_source.py --provider aliyun --enabled-only --dry-run
.\.venv312\Scripts\python scripts\ingest_source.py --provider aliyun --enabled-only --force
.\.venv312\Scripts\python scripts\parse_product_sources.py --provider aliyun
.\.venv312\Scripts\python scripts\generate_data_quality_report.py --provider aliyun --product ecs
.\.venv312\Scripts\python scripts\generate_data_quality_report.py --provider aliyun --product oss
.\.venv312\Scripts\python scripts\validate_provider_market_scope.py --provider aliyun
.\.venv312\Scripts\python scripts\validate_region_zone_relationships.py --provider aliyun
.\.venv312\Scripts\python scripts\validate_provider_partitions.py --provider aliyun
.\.venv312\Scripts\python scripts\generate_manual_review_sample.py --provider aliyun
```

## Week 6 Canonical Normalization Commands

Set `DATABASE_URL` to a database upgraded to Alembic head before running the
database-backed commands.

```bash
.\.venv312\Scripts\python scripts\validate_canonical_definitions.py
.\.venv312\Scripts\python scripts\generate_field_matrix.py
.\.venv312\Scripts\python scripts\build_week6_combined_acceptance.py
.\.venv312\Scripts\python scripts\normalize_provider_data.py --source-database-label week6_combined_projection --run-key week06_combined_projection_normalization
.\.venv312\Scripts\python scripts\validate_canonical_units.py
.\.venv312\Scripts\python scripts\validate_value_qualifiers.py
.\.venv312\Scripts\python scripts\validate_specification_scopes.py --summary-only
.\.venv312\Scripts\python scripts\validate_normalized_evidence.py
.\.venv312\Scripts\python scripts\generate_cross_provider_coverage.py
.\.venv312\Scripts\python scripts\generate_normalization_quality_report.py
```
