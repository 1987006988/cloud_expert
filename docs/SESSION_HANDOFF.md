# Session Handoff

## Closure Remediation Handoff (2026-09-30, Current)

Start with `tasks/week11_16_closure.yaml` and its latest immutable checkpoint,
not the historical GO/test counts below. Preserve the dirty checkout and all
original evidence/review history. Coordinator-only business database writes apply.

- Business database is `test_outputs/week6_combined_projection.sqlite` at 0014;
  post-replacement backup and hash receipt are recorded in
  `reports/remediation/closure_20260930/database_checkpoint_03.json`.
- AWS replacements are 13 -> 19, 17 -> 20, 18 -> 21, with independent preview,
  apply and repeat directories `aws_price_<old-id>_<phase>_01`. Reuse saved plan
  hashes for retries, never edit historical prices or vendor effective dates.
  Current consumption requires the live raw/document/registry/receipt proof;
  superseded history is visible but not selectable. Prices 1 and 14-16 remain gaps.
- AWS EC2 parser v2 refreshed snapshots 117/118 and runs 133/134. Downstream
  reports: `aws_ec2_normalization_v2_01.json`, `comparability_aws_v2_02.json`,
  `mapping_aws_v2_02.json`, `evidence_packages_aws_v2_02.json`. Reparse history is
  not an approval and must not be deleted to reduce queue counts.
- Independent price-code review found an autoflush side effect in read-only
  validation; it was fixed and independently rechecked with zero SQL/flush in
  dirty/new/deleted sessions. Keep these regression cases.
- PostgreSQL `postgres_03/junit.xml` has 10 real passes. Final offline verification
  must use a sealed, clean, unchanged-input bundle from `reports/verification/`;
  retain failures and never substitute its unit results for full-chain Eval.
- Owner permits only the internal-RC model audit alternative, with frozen input,
  actual model identity, complete responses, hashes and per-release Eval. Do not
  assert an immutable gpt-6-astra version, model approval, customer authority or
  automatic GO from this permission.
- Huawei browser SSO has expired. Await owner login for a new readonly inquiry;
  do not transfer credentials, account-specific discounts or private response data.
  Preserve the 730h/720h and GB/GiB distinctions in all comparisons.
- Next prerequisites are remaining official cost/unit scopes, current review queue
  disposition, fresh same-scenario TCO/Decision and actual independent model review.
  Gate failures still block downstream sales/UI/release work. Real pilot remains
  deferred, and an internal-engineering/customer Gate split is awaiting owner policy.

## Component Follow-up (2026-09-30, Earlier)

Read `reports/remediation/closure_20260929/component_price_followup.md` first.
The owner deferred real internal pilot participation; see `docs/PILOT_DEFERRAL.md`.
Do not claim offline/model tests are real-user feedback or weaken unrelated Gates.

- Business DB remains `test_outputs/week6_combined_projection.sqlite` at 0014.
- New price IDs 7-9 are Huawei 730h compute/disk and 100GB outbound quotes,
  derived Evidence 14201-14203, source quote Evidence 14191-14193.
- New price IDs 10-12 are Aliyun bounded non-real-time catalog estimates,
  derived Evidence 14204-14206, catalog Evidence 14160/14163/14190 and tax 14199.
- Catalog snapshot 85; Huawei component inquiry snapshot 86; support/unit/tax
  policies 87-91. All imports and promotions have independent repeat reports.
- Do not extrapolate the 720h Aliyun bound to 730h, equate GB with GiB, or count
  unbound Huawei IP quote 14194 as a bound-instance cost. Basic-support/free-IP
  clauses alone do not authorize arbitrary zero-cost lines.
- Latest actual price/Eval/Week11 checks are in `component_validation/`;
  PostgreSQL 8 passes in `postgres_03/`. `tests_09/` retains the one old-registry
  count failure. Final `tests_10/` passed 291 tests, zero failures, 86.09% combined
  line/branch coverage. Ruff and strict mypy (300 files) pass.
- Full TCO/Decision review/UI/release remain unclosed. Model alias still lacks
  a verified immutable snapshot. No commit/push or release was made this turn.

## Price Follow-up Handoff (2026-09-29, Earlier)

The new current report is `reports/remediation/closure_20260929/price_promotion_and_tco.md`.
Do not repeat login, tax-policy discovery or already applied price promotions.
The business DB is still `test_outputs/week6_combined_projection.sqlite` at 0014.

- Real price evidence: tax 14153; bounded prices 14154-14157 and 14159;
  separate 730h quote 14158. PriceSnapshot IDs 2-6; five new Huawei rows.
- `scripts/promote_huawei_quotes.py` requires explicit quote/unit IDs and
  a new report directory; use dry-run first. Historical dry-run/apply/repeat
  outputs exist, as does the pre-promotion SQLite backup.
- `scripts/generate_domestic_price_readiness.py` has dry-run and controlled apply.
  Actual runs 4/5 contain ECS known cost 335.80, OBS known cost 50.02, missing
  dimensions and NULL totals. They are internal assumptions, not customer TCO.
- Current tests: `tests_08/` (255 passed, 85.7727%) and `postgres_02/` (8 passed).
  Gate verification copies refreshed; prior copies in `pre_price_verification/`.
- Domestic Decision run `domestic_general_compute_research_v1_v1_v1_6eb028525048`
  has 391 internal-only candidates, none eligible. It did not justify model
  approval or queue closure. The existing review queue/history is preserved.
- Latest Gates: Week12 `run_55ed393ad167`, Week14 `run_287ef8408e48`.
  Week11-16 are still NO-GO. Next work is missing official cost scopes,
  scenario-matched complete TCO, real independent Decision review and queues,
  then full-chain Eval/UI/release/pilot under the original admission conditions.
- Raw API captures remain local and Git-ignored. API Explorer uses working SSO;
  unattended Token access is still not configured. Do not export project IDs,
  headers, tokens or account discount payloads to model review.

## Closure Handoff (2026-09-29, Earlier)

The newest Project State and `reports/remediation/closure_20260929/closure_status.md`
supersede the pilot-only notes below. Preserve all existing dirty work and
historical reports. No commit/push was requested during this remediation turn.

- Business database: `test_outputs/week6_combined_projection.sqlite`, revision
  0014. Set DATABASE_URL explicitly for business scripts. Do not use the empty
  default development database as evidence of project readiness.
- Mapping 649 replaces 415 with new Evidence and has a real independent
  conditional model approval, report
  `reports/model_review/week14_pilot/mapping_649_2688b1390b6c/`.
  Scoped approval is now supported by the controlled apply command; approval
  integrity and current provenance are rechecked at downstream consumption.
  Legacy human review fields are deliberately unchanged.
- Backups before revision/writeback:
  `test_outputs/closure_before_mapping_415_revision.sqlite` and
  `test_outputs/closure_before_scoped_approval.sqlite`.
- Tests are in `reports/remediation/closure_20260929/tests_07/` (234 passed,
  85.7956% coverage) and `postgres_01/` (8 passed). Earlier failed/passing runs
  are preserved. Gate verification files were refreshed from these actual
  outputs, with prior copies archived under `prior_verification/`.
- Official API Explorer login succeeded. Actual ECS/OBS price queries returned
  HTTP 200, were saved locally without credentials/project IDs, and imported
  through `scripts/import_huawei_api_ui_capture.py`. SourceDocument/Snapshot
  80-82, Evidence 14145-14152; repeat import is idempotent. These are explicitly
  UI clipboard copies, not wire captures. Failure/discovery artifacts remain
  in `test_outputs/huawei_pricing_api/`. Pre-import DB backup:
  `test_outputs/closure_before_huawei_api_capture.sqlite`.
- Next: resolve tax, tier and OBS billing-time evidence, then controlled
  PriceSKU/PriceSnapshot promotion; obtain missing competitor dimensions and
  rerun pricing/TCO/Decision and reviews. Do not ask for login again as a
  prerequisite already completed. Unattended Token access is still unconfigured.
  Account discounts/raw account responses must stay local, outside model inputs.
- Week9/10 internal Gates now pass. Week14 mode is `review_migration`, latest
  `reports/week14_gate/runs/run_d37b4b59efba/`. Week11-16 remain NO-GO.
  See `reports/remediation/closure_20260929/huawei_api_capture.md` for exact scope.
- Remaining model queue and model-alias provenance limits are real, not reasons
  to relabel every row approved. UI/production/pilot remain unimplemented.

## Authorized Pilot Handoff (2026-09-29)

The current state is the first section of `docs/PROJECT_STATE.md`. The owner
authorized only official excerpts, mapping candidates, and necessary IDs for
OpenAI `gpt-6-astra` review. `config/model_review/review_authorization.yaml`
is now true for that scope, not for customer data, secrets, or customer output.
Do not rerun a pilot against new target types without an equivalent payload
allowlist and provenance check.

Use `DATABASE_URL=sqlite:///./test_outputs/week6_combined_projection.sqlite`
for read/write Gate work, but clear it before running the full migration test
suite. The projection remains at Alembic 0014 and now has 11,342 assignments,
11,343 audit events, and one `model_inconclusive` assignment (candidate 415).
The pre-writeback copy is
`test_outputs/week14_before_pilot_415_writeback.sqlite` (ignored). The pilot
report is `reports/model_review/week14_pilot/mapping_415_8281871ee244_run_03/`;
the first two attempts are preserved as technical failures. The separate
`apply_week14_pilot_result.py` command is idempotent and cannot apply approval.

The ECS description parser and product identity lookup have been repaired.
The active projection was backed up at
`test_outputs/week14_before_ecs_description_reparse.sqlite`, then the Huawei
and Aliyun ECS introduction sources were reparsed. New description Evidence
14143 and 14144 coexists with old Evidence 52 and 13965; `Product.description`
is populated for both. Source snapshot hashes, 11,563 normalized Evidence
links, and the 11,343-event model-review audit all validate. The mapping
generator now selects the product-definition Evidence, but existing mapping
candidate links and precheck hashes are unchanged. Do not silently mutate
candidate 415 or reuse its inconclusive review for a new evidence set.

Current tests: 143 non-network passes, 8 previously passing PostgreSQL tests,
73.7578% coverage. Latest Week14 Gate report:
`reports/week14_gate/runs/run_7e2950e06e2f/`; verdict remains NO-GO. Next
work is versioned mapping-candidate regeneration, new deterministic prechecks
and independent model reviews, remaining repair queue, fresh price/TCO/customer
chain, full-chain Eval, and the 85% coverage threshold. Week15/16 stay blocked.

## Week 14 Handoff (2026-09-29)

The authoritative state is the Week14 reassessment in `docs/PROJECT_STATE.md`.
Run the project against
`DATABASE_URL=sqlite:///./test_outputs/week6_combined_projection.sqlite`;
the projection is now at Alembic `0014_week14_review_workflow`. A pre-migration
copy exists at `test_outputs/week14_pre_migration_backup.sqlite` (ignored).

Review migration is additive and idempotent: 11,342 assignment/audit pairs,
with 1,010 pending model review and 10,332 deterministic blocks. The legacy
human rows remain untouched. The highest-model probe succeeded after updating
Codex CLI, but the exact snapshot version is unresolved. Do not attempt the
Evidence-bearing model pilot while
`config/model_review/review_authorization.yaml` says external transfer is
unapproved; a safety reviewer rejected the attempt. Do not route around it.

The 37-case deterministic Eval subset passed, but full-chain coverage is
false. The current test evidence is 134 non-network passes, 8 PostgreSQL
passes, and 73.0695% coverage. Week14 is `NO-GO`; no customer output or
Streamlit business UI is authorized. Next priorities are explicit data-transfer
approval, full model-stage audit/writeback, parser-root-cause repair from
snapshots, current official price/TCO closure, broad Eval coverage, and raising
current test coverage to 85%. Preserve all historical data and reports.

## Current Handoff (2026-09-29)

Use the dated reassessment in `docs/PROJECT_STATE.md` instead of the historical
Week10-only summary below. The current work has an evidence-first dual-model
review pilot, controlled rejection writeback, market-scope reference records,
domestic mapping-rule repair with preserved history, recomputed
evidence/decision outputs, and fresh Gate reports. Week11, Week12, and Week13
remain `NO-GO`.

The active database is `test_outputs/week6_combined_projection.sqlite` via
`DATABASE_URL=sqlite:///./test_outputs/week6_combined_projection.sqlite`.
Do not point writeback tools at the empty default development database.
PostgreSQL verification used an isolated database named
`cloud_expert_r011_week12_20260929`, not the projection. The current full-suite
coverage is 73.4908% against an 85% gate. All 127 non-network,
non-PostgreSQL tests passed; the seven PostgreSQL tests passed
separately after a fresh upgrade, downgrade -1, upgrade, downgrade base, and
upgrade cycle. No customer output or Streamlit business page is authorized.

Current Week12 repair evidence is under
`reports/market/mapping_scope_repair/run_20c094eee175/` and
`reports/market/quality/run_6fd902754ccb/`. The generator now distinguishes
same-market from cross-market mappings; 234 old mislabeled rows were
superseded, not deleted. Active mapping scope errors are zero. The domestic
compute scenario is internal-only and does not fabricate price evidence.

Next work is substantive, not a label change: source-backed reparsing of the
four sampled ReviewItems, individual dual-model review of the remaining queue,
fresh official price snapshots and joined TCO/decision evidence, plus coverage
improvement. Preserve every historical review and migration record. The
Streamlit business pages remain blocked by the Week13 prerequisite Gate.

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
