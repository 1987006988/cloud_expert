# Session Handoff

## Summary

Remediation Stage 1 is partially complete after the Week 1-6 independent audit.
The repository now has a Git delivery baseline, a rebuilt default SQLite
database at Alembic head, restored Week 6 evidence provenance, Stage 1
validation scripts, reports, and updated governance documents. The stable
checkpoint is commit `fa75ded`.

`WEEK7_GATE=NO-GO`

No new cloud providers, pricing ingestion, TCO, RAG, embeddings, LLM logic,
frontend, sales scripts, competitive scoring, customer data, console/session
data, credentials, or final product mapping were added.

## Key Files

- `alembic/versions/0006_week06_canonical_normalization.py`
- `src/cloud_expert/database/models/canonical.py`
- `src/cloud_expert/normalization/canonical_fields.py`
- `src/cloud_expert/normalization/unit_standardization.py`
- `src/cloud_expert/normalization/canonical_service.py`
- `src/cloud_expert/normalization/reports.py`
- `scripts/validate_canonical_definitions.py`
- `scripts/normalize_provider_data.py`
- `scripts/build_week6_combined_acceptance.py`
- `scripts/inspect_database_schema.py`
- `scripts/validate_default_database.py`
- `scripts/relink_normalized_evidence.py`
- `scripts/validate_week06_projection.py`
- `scripts/generate_field_matrix.py`
- `scripts/generate_cross_provider_coverage.py`
- `scripts/generate_normalization_quality_report.py`
- `reports/normalization/`
- `docs/CANONICAL_DATA_MODEL.md`
- `docs/CANONICAL_FIELDS.md`
- `docs/UNIT_NORMALIZATION.md`
- `docs/COMPARABILITY_POLICY.md`
- `docs/COMPUTE_CANONICAL_MODEL.md`
- `docs/OBJECT_STORAGE_CANONICAL_MODEL.md`
- `docs/REGION_NORMALIZATION.md`
- `docs/GIT_BASELINE_POLICY.md`
- `docs/DATABASE_RECOVERY.md`
- `docs/POSTGRESQL_VALIDATION.md`
- `docs/WEEK06_EVIDENCE_RELINK.md`
- `docs/WEEK06_PROJECTION_CONTRACT.md`
- `reports/remediation/stage1/`

## Migration Version

- Revision: `0006_week06_canonical_normalization`
- New app tables: `canonical_field_definition`, `normalization_rule`,
  `normalization_run`, `normalized_specification`, `comparability_assessment`
- Total application tables: 34

## Verification Results

Final local commands passed:

```text
ruff format .
ruff check .
mypy src scripts
pytest --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports/remediation/stage1/coverage.json
scripts/validate_source_registry.py
scripts/validate_raw_snapshots.py
scripts/validate_canonical_definitions.py
scripts/validate_canonical_units.py
scripts/validate_value_qualifiers.py
scripts/validate_normalized_evidence.py
scripts/validate_week06_projection.py
scripts/validate_default_database.py
alembic upgrade head
```

PostgreSQL live validation is not complete. `docker compose config` passed, but
Docker daemon connection failed at `//./pipe/docker_engine`.

Week 6 combined projection result:

- Canonical fields: 38.
- Normalization rules: 40.
- Normalized specifications: 10172.
- Skipped specifications: 240.
- Pending-review normalized rows: 768.
- Scope mismatch warnings: 90.
- Comparability assessments: 116.
- Comparability status counts: 13 comparable, 66 partial, 37 not comparable.
- Missing normalized evidence links: 0.
- Missing snapshot records/manifests/raw files/hash mismatches: 0.
- Average normalization quality score: 0.9781.

## Environment Notes

- Python used for final verification: 3.12.13.
- Local project verification environment: `.venv312`.
- Raw snapshots are generated under `data/raw` and ignored by Git.
- Week 6 combined projection database:
  `test_outputs/week6_combined_projection.sqlite`.
- Source acceptance copies upgraded for projection:
  `test_outputs/week6_source_huawei_upgraded.sqlite`,
  `test_outputs/week6_source_aws_upgraded.sqlite`, and
  `test_outputs/week6_source_aliyun_upgraded.sqlite`.

## Unresolved Issues

- PostgreSQL live migration validation remains open until Docker is available.
- Coverage is 79%, below the 85% backlog target.
- Stage 2 Canonical schema/enums, qualifier/scope, ComparabilityAssessment,
  Field Matrix, and ReviewItem governance remain open.
- Prior human review queues remain open.
- Object storage service-tier scope needs a direct key in future schema or
  parser output before final service-tier comparison.
- Huawei Region evidence remains product-level and unstructured in the Week 3
  acceptance data.

## Next Session Starting Point

Start from `docs/CANONICAL_DATA_MODEL.md`,
`reports/normalization/normalization_quality_report.json`, and
`reports/remediation/stage1/00_summary.md`. Do not turn readiness
assessments into customer-facing product comparisons until human review,
scope policy, PostgreSQL validation, coverage, and mapping policy are approved.
