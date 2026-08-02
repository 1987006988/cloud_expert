# Session Handoff

## Summary

The local workspace now includes Week 10 internal scenario decision engine
delivery on top of the completed Week 1-9 remediation, mapping, evidence
package, pricing, and TCO work.

Gate status in the local projection database:

```text
WEEK7_GATE=GO
WEEK8_GATE=GO
WEEK9_GATE=GO
WEEK10_GATE=GO
```

Week 10 added Alembic revision `0010_week10_decision_engine`, 5 standard
decision scenarios, 5 versioned scoring policies, 5 decision runs, and 1,230
machine-generated internal candidate results. All results remain
`internal_only`; customer-eligible decision candidates remain 0.

No sales scripts, opponent attack material, customer commitments, RAG,
embeddings, frontend, customer data, console/session data, credentials,
discounts, or final bid recommendations were added.

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
- `scripts/check_database_connection.py`
- `scripts/generate_field_matrix.py`
- `scripts/generate_cross_provider_coverage.py`
- `scripts/generate_normalization_quality_report.py`
- `scripts/export_review_package.py`
- `reports/normalization/`
- `reports/remediation/stage2/`
- `D:\审核文件`
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
- `alembic/versions/0010_week10_decision_engine.py`
- `src/cloud_expert/database/models/decision.py`
- `src/cloud_expert/decision/`
- `config/decision/`
- `scripts/check_week10_gate.py`
- `scripts/run_decision_engine.py`
- `scripts/validate_decision_evidence.py`
- `scripts/validate_decision_idempotency.py`
- `reports/week10_gate/`
- `reports/decision/`
- `reports/review_samples/week10_decision_review.csv`

## Migration Version

- Revision: `0010_week10_decision_engine`
- New Week 10 app tables: `decision_scenario`, `scenario_requirement`,
  `scoring_policy`, `scoring_rule`, `decision_run`,
  `candidate_decision_result`, `dimension_score`, `rule_evaluation`,
  `decision_review`, `decision_sensitivity_result`
- Total application tables: 52

## Verification Results

Final local commands passed:

```text
ruff format .
ruff check .
mypy src scripts
pytest --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports/remediation/r011/runs/run_02/coverage.json
scripts/validate_source_registry.py
scripts/validate_raw_snapshots.py
scripts/validate_canonical_definitions.py
scripts/validate_canonical_units.py
scripts/validate_value_qualifiers.py
scripts/validate_normalized_evidence.py
scripts/validate_week06_projection.py
scripts/validate_default_database.py
alembic upgrade head
scripts/export_review_package.py --output-dir D:\审核文件
```

R011 PostgreSQL live validation passed in `run_02`:

- Docker Desktop PostgreSQL container healthy.
- SQLAlchemy connection check passed.
- fresh PostgreSQL upgrade to head passed.
- downgrade `-1` and re-upgrade passed.
- downgrade base and re-upgrade from base passed.
- schema fingerprints matched after excluding database URL.
- `pytest -m postgres -ra` passed, 6 tests.
- `pytest -m "not network" -ra` passed, 83 tests and skipped 6 PostgreSQL
  tests when `POSTGRES_TEST_DATABASE_URL` was not set.

Week 6 combined projection result:

- Canonical fields: 38.
- Normalization rules: 40.
- Normalized specifications: 10172.
- Skipped specifications: 240.
- Pending-review normalized rows: 678.
- Scope mismatch warnings: 0.
- Comparability assessments: 116.
- Comparability status counts: 13 comparable, 64 partial, 37 not comparable,
  2 needs_review.
- Missing normalized evidence links: 0.
- Missing snapshot records/manifests/raw files/hash mismatches: 0.
- Average normalization quality score: 0.9798.

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

- R008 remains `pending_human_review`. Review package:
  `D:\审核文件\review_manifest.json`.
- Prior human review queues remain open in the database until reviewer
  decisions are applied.
- Huawei Region evidence remains product-level and unstructured in the Week 3
  acceptance data.

## Next Session Starting Point

Start from `docs/CANONICAL_DATA_MODEL.md`,
`reports/normalization/normalization_quality_report.json`,
`reports/remediation/stage2/00_summary.md`, and
`D:\审核文件\REVIEW_INSTRUCTIONS.md`. Do not turn readiness assessments into
customer-facing product comparisons until human review decisions are applied
and Week 7 gate is explicitly reopened.
