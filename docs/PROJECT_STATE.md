# Project State

## Closure Remediation (2026-09-30, Current)

This section supersedes the historical checkpoints below. The active scope is
`docs/WEEK11_16_CLOSURE_CHECKLIST.md`; the business database remains
`test_outputs/week6_combined_projection.sqlite`, revision 0014. Current machine
results and immutable run records are under `reports/remediation/closure_20260930/`.

- The owner authorized an internal-RC-only model-alias audit alternative, recorded
  in `config/model_review/reproducibility_policy.yaml`. This is not customer-use
  authority, immutable-model-version evidence, or a Gate pass.
- AWS website policy acquisition was retired after its terms recheck. Approved
  catalog inputs are retained, and licensed documentation supports bounded request
  and compute derivations. Price 13 -> 19, 17 -> 20 and 18 -> 21 were appended with
  transaction receipts; all three repeat applies created zero rows. Old prices,
  source dates and review history were preserved. S3 storage prices 1 and 14-16
  still need admissible billing-unit/tier remediation. Structural linkage alone
  does not prove a currently usable price.
- Fresh AWS EC2 snapshots 117/118 were reparsed with strict header-bound numeric
  memory and CPU-architecture checks. Normalization, comparability, mapping and
  evidence packages were rebuilt. The 683 newly parsed memory values passed the
  numeric/unit check; ambiguous facts and historical review items were not approved.
- Ten actual PostgreSQL integration tests passed, including rollback and concurrent
  price-replacement idempotence. See `postgres_03/junit.xml`. This is an isolated
  test database, not production deployment or a SQLite substitute.
- Offline verification bundles separately retain code/config/input hashes, JUnit,
  coverage and tool receipts under `reports/verification/`. Only a clean bundle
  with unchanged inputs may support the tested version. Failed or drifting runs
  remain historical; unit coverage is not full-chain Eval or Model Judge.
- Database backup `test_outputs/closure_after_price_replacement_20260930.sqlite`
  passed its integrity check; `database_checkpoint_03.json` records its hash and
  counts. Raw files and database backups remain local, outside Git.

Recorded Week9-16 Gates remain NO-GO. No fresh approved Decision, sales-ready
dependency chain, Streamlit business workbench, RC deployment or real pilot is
claimed. Huawei API Explorer requires owner login for a fresh harmonized quote.
Real pilot participation stays `deferred_by_owner`; internal/customer Gate
separation requires its own policy decision and is not inferred from the alias
exception. Use the latest checkpoint in `tasks/week11_16_closure.yaml` for the
precise remaining work and verification results.

## Component Prices (2026-09-30, Earlier)

The current report is `reports/remediation/closure_20260929/component_price_followup.md`.
Six additional PriceSKUs/PriceSnapshots (7-12) now have bounded official inquiry
or explicitly non-real-time catalog evidence. New SourceDocument/Snapshots 85-91
and Evidence 14160-14206 preserve the source, tax and unit chain. All 12 price
snapshots pass the current evidence validator; repeat import/promotion creates
no duplicates. The earlier incomplete TCO runs are preserved, not relabeled.

No cross-vendor cost advantage is asserted: quote periods, disk units and price
bases differ. Week11 remains NO-GO on the five recorded downstream blockers;
Weeks 12-16 are not complete. Real participant feedback is deferred by owner,
not model-simulated. PostgreSQL integration passed 8 tests; offline Eval passed
37 cases but explicitly remains short of full-chain coverage. Final offline
regression passed 291 tests with 86.09% combined line/branch coverage; Ruff and
strict mypy (300 files) also pass.

## Pilot Scope Amendment (2026-09-29)

The owner explicitly deferred the real internal pilot because participants and
business opportunities are not currently available. Technical readiness work
continues under existing gates; offline/model/browser/restore rehearsals will
not be reported as real-user feedback or a completed real pilot. See
`docs/PILOT_DEFERRAL.md`. This amendment changes scope, not any measured Gate.

## Price Closure Follow-up (2026-09-29, Earlier)

This section supersedes the prior price and test status below, preserving history.
See `reports/remediation/closure_20260929/price_promotion_and_tco.md`.

- Official tax inclusion and separate 730-hour inquiry evidence were captured.
  SourceDocument/Snapshot 83-84, Evidence 14153-14159 extend the existing chain.
  Five bounded Huawei PriceSKUs/PriceSnapshots were actually promoted; repeat
  import/promotion is idempotent. No credential/account-discount transfer occurred.
- Domestic cost runs 4/5 now show known CNY subtotals 335.80 (ECS instance)
  and 50.02 (OBS requests/egress). Both remain missing-price, NULL-total results;
  OBS storage-time evidence, other components and competitor coverage are incomplete.
- Currency, tax-scope, future-price, timestamp and exact-quantity checks were fixed.
  Domestic Decision was rerun: 391 candidates, zero customer-eligible results.
- Current regression: 255 offline passes, 85.7727% combined line/branch coverage;
  8 actual PostgreSQL integration passes, Ruff and strict mypy pass.
- Week11-16 still NO-GO. Week12 only has its Week11 blocker. Latest Week12 run
  `run_55ed393ad167`, Week13 `run_43f587703963`, Week14 `run_287ef8408e48`.
  Week15/16 updated admission-only reports are under `runs/price_followup_20260929/`.
  No UI, release or real pilot completion is claimed.

## Closure Reassessment (2026-09-29, Earlier)

This section supersedes earlier current-status sections without deleting their
history. See `reports/remediation/closure_20260929/closure_status.md`.

- Offline suite: 234 passed, zero failed; measured line/branch coverage
  85.7956%. PostgreSQL integration: 8 passed. Ruff checks and strict mypy pass.
- Candidate 415 was superseded, not rewritten. New candidate 649 cites repaired
  official definition Evidence 14143/14144. Independent `gpt-6-astra` primary and
  adversarial reviews both conditionally approved product-category equivalence.
  Audit event 11346 enforces that narrow scope; no SKU/price/SLA/performance
  equivalence or human review was asserted. One active evidence package now
  qualifies for that scope, but no customer DecisionResult is approved.
- Review audit: 11,343 assignments, 11,346 events, valid. The queue contains
  1,009 pending, 10,332 deterministically blocked, one superseded, and one
  conditionally approved assignment. Normalized evidence: 11,563 records,
  37 raw files checked, zero missing links/files or hash mismatches.
- TCO now aggregates dimensions per product, preserves missing prices and
  unknown tax as NULL, and rejects unsupported tiers/mixed currencies. Complete
  results require declared scenario scope and current evidence. Snapshot path
  escape and hash-tampering checks are enforced before price extraction.
- Authorized ECS and OBS official API queries succeeded (HTTP 200). Copied
  response snapshots 80-82 and Evidence 14145-14152 are linked and retained;
  credentials/request headers were not exported. Browser authentication is
  working; unattended Token access is not configured. No new Huawei PriceSKU
  or PriceSnapshot was promoted because tax, tier and OBS time scope remain
  unresolved. See `reports/remediation/closure_20260929/huawei_api_capture.md`.
  Old website sources remain disallowed; approved API replacements satisfy
  collection readiness without changing the historical restrictions.
- Week7-10 are internal GO. Week11-16 remain NO-GO. Week12 coverage, PostgreSQL, and market
  checks now pass; its only remaining blocker is Week11. Week14 is in
  `review_migration` mode with no Week9/10 hard stop. No Streamlit business UI, Release Candidate,
  production deployment, or real pilot has been completed.

Latest reports: Week12 `runs/run_fc22c2c12671`, Week13
`runs/run_43f587703963`, Week14 `runs/run_d37b4b59efba` under their Gate folders.

## Authorized Week 14 Pilot Reassessment (2026-09-29)

The owner explicitly authorized transfer of official-source excerpts, mapping
candidates, and necessary identifiers to OpenAI `gpt-6-astra` for independent
review. Customer data and secrets remain excluded; customer-output approval
was not granted. This section supersedes the older Week 14 authorization and
test counts below, but not their preserved historical evidence.

- Mapping candidate 415 completed isolated primary, adversarial, and
  adjudication runs. All three stages had distinct session IDs and validated
  Evidence IDs. The final decision is `model_inconclusive`: the cited SKU rows
  do not establish a product-level relationship. No mapping approval or
  customer eligibility was written.
- Two earlier attempts remain recorded as technical failures. Windows
  subprocess input now uses UTF-8 stdin, and timeout reasons no longer copy
  source excerpts into the summary. A consensus bug that forced reparse before
  considering adjudication was corrected with a recorded correction.
- The final nonapproval was applied only to the model-review overlay. It
  appended audit event 11343 and changed assignment 415 to
  `model_inconclusive`; a repeated apply was idempotent. Legacy human rows,
  `MappingCandidate`, and downstream business results were not modified.
- The queue is now 1,009 pending, 10,332 deterministically blocked, and one
  inconclusive. Inconclusive and conditionally approved states explicitly
  remain Week 14 Gate blockers.
- Current non-network suite: 143 passed; isolated PostgreSQL suite: 8 passed.
  Current measured coverage is 73.7578%, below 85%. A failed migration-test
  run caused by inherited `DATABASE_URL` was archived; migration tests now
  isolate their own temporary database, and the full rerun passed.
- ECS product-description extraction now selects definition paragraphs over
  navigation text. Controlled reparse of the unchanged official snapshots
  created Huawei Evidence 14143 (`html:text[194]`) and Aliyun Evidence 14144
  (`html:text[66]`), preserving old Evidence 52 and 13965. Both product
  descriptions are now populated; raw snapshot hashes and the review audit
  remain valid. The mapping generator now selects product-level description
  Evidence instead of SKU rows, but existing candidate links and downstream
  decisions were not rewritten.
- Week7/8/9/10 are GO for internal engineering. Week11/12/13/14 remain NO-GO;
  Week15/16 remain admission-report-only NO-GO. No Release Candidate, pilot,
  customer output, or production deployment is authorized.

Evidence: `reports/model_review/week14_pilot/pilot_assessment.md`,
`reports/week14_gate/runs/run_7e2950e06e2f/`,
`reports/remediation/ecs_description_parser_repair.md`, and
`reports/remediation/all_weeks_gate_status.md`.

## Week 14 Reassessment (2026-09-29)

`WEEK14_GATE=NO-GO`, running in `review_migration` mode. Week9/10 remain GO;
Week11/12/13 remain NO-GO. This section supersedes the Week12-only current
snapshot below for review and test counts.

- Codex CLI was updated from 0.121.0 to 0.158.0. A read-only, data-free
  `gpt-6-astra` probe at `max` reasoning succeeded. No weaker fallback was used;
  the exact model snapshot behind the alias remains unresolved.
- Alembic 0014 adds an additive review-assignment and audit overlay. The
  current precheck's 11,342 findings were migrated: 1,010 pending model review,
  10,332 blocked by deterministic checks, zero missing targets. A second apply
  created zero rows. Legacy review statuses were not modified.
- The real Evidence-bearing model pilot was rejected by environment safety
  review because it would transmit local review data externally. The pilot is
  disabled by configuration. There are zero new Week14 primary, adversarial,
  or adjudication opinions and zero model approvals/writebacks.
- The synthetic deterministic Eval subset has 37 unique cases, all passing.
  It does not cover the full chain or run a Model Judge; no unmeasured fact or
  customer-output metric is presented as passed.
- Current non-network tests: 134 passed; isolated PostgreSQL tests: 8 passed.
  Fresh PostgreSQL migration round trips through 0014, including downgrade
  base and upgrade head, passed. Current line/branch coverage is 73.0695%,
  below 85%.
- The Week14 Gate still blocks on unapproved data transfer, open review and
  repair queues, Week11-13 dependencies, incomplete Eval coverage, unpinned
  model alias, and code coverage. Customer output and Week15 production
  hardening are not authorized.

Evidence: `reports/model_review/model_resolution.json`,
`reports/model_review/migrations/`, `reports/evals/eval_results.json`, and
`reports/week14_gate/runs/`. See `docs/MODEL_REVIEW_ARCHITECTURE.md` for the
precise limitations.

## Current Reassessment (2026-09-29)

This section supersedes older readiness and coverage claims below. The active
projection is `test_outputs/week6_combined_projection.sqlite`; the default
development SQLite database is not the populated acceptance projection.

- `WEEK9_GATE=GO`, `WEEK10_GATE=GO`, `WEEK11_GATE=NO-GO`,
  `WEEK12_GATE=NO-GO`, `WEEK13_GATE=NO-GO`.
- Two independent `gpt-6-astra` panels individually reviewed six sampled
  subjects: two rejections and four reparse requirements. The latest
  deterministic precheck has 11,342 findings; those findings are not
  individual dual-model approvals. Model findings retain their model label;
  historical human review rows are unchanged.
- Rejections for mapping candidate 5 and decision result 3 were written back
  with model-labelled review records. Four ReviewItems remain unresolved.
- Market validation passes for active data: 54 reference contexts, 1,485
  compatibility assessments, no missing source partitions, no unknown Region
  countries, no active mapping scope errors, and no active TCO market mismatch.
  The mapping generator now selects domestic/international RuleSets for
  same-market products. Its 234 previously mislabeled domestic candidates
  are superseded by 234 new domestic candidates, with history retained. Eight
  historical TCO market mismatches remain visible.
- There are 413 active Evidence Packages, with no active rejected-value link
  or false full-completeness flag. An internal synthetic domestic compute
  scenario runs through the Decision Engine, but all 391 candidate results
  remain internal-only; there is no customer-eligible result.
- Fresh PostgreSQL migration round trips and seven isolated integration tests
  passed at Alembic head `0013_week12_market_context`.
- The current full non-network, non-PostgreSQL suite passed 127 tests. The
  seven PostgreSQL tests passed in their isolated run. Measured combined
  line/branch coverage is 73.4908%, below the 85% gate. The earlier 85%
  statement below describes an older tree and is not current evidence.
- The only official price snapshot in the projection is stale. There are no
  fresh complete customer TCOs, approved model mappings/decisions, or customer
  outputs. Week11 and its successor Gates remain closed.

Current evidence: `reports/model_review/round_02/`,
`reports/remediation/week11_model_review/model_review_7a317e83b89979fd/`,
`reports/market/mapping_scope_repair/run_20c094eee175/`,
`reports/market/quality/run_6fd902754ccb/`,
`reports/week11_gate/validation_results.json`,
`reports/week12_gate/runs/run_dce18f7768b0/`, and
`reports/week13_gate/runs/run_fcfc9ff4d89e/`.

The Week12 blockers are Week11's unresolved evidence/price/approval/customer
chain and current coverage below 85%. The only price snapshot is stale, no
current TCO has complete fresh price lines, and the Sales Artifact chain is
not implemented. Waiving manual review does not create model approval or
official price evidence. Week13's mandatory prerequisite is therefore unmet;
no Streamlit business page is authorized.

## Historical Phase Summary

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
