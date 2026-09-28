# Week 12 Dependency Status

| Dependency | Status | Evidence |
| --- | --- | --- |
| Week 9 Gate | GO | `reports/week09_gate/validation_results.json` |
| Week 10 Gate | GO | `reports/week10_gate/validation_results.json` |
| Week 11 Gate | NO-GO | `reports/week11_gate/validation_results.json` |
| Controlled human-review import | Present | 1 batch, 2,222 decisions |
| Review audit history | Present | 2,222 before/after audit rows |
| Model review audit | Present, internal only | 1 run, 5,154 findings; no human-review substitution |
| Parser remediation | Passed | Active bad AWS memory rows 0; Aliyun Zone name/code collisions 0 |
| Mapping human review | Missing | 0 human-reviewed MappingCandidate rows |
| Customer-eligible evidence | Missing | 0 customer-eligible EvidencePackage rows |
| DecisionResult human review | Missing | 0 DecisionReview rows |
| Customer-eligible decisions | Missing | 0 customer-eligible CandidateDecisionResult rows |
| Week 11 sales artifact chain | Not ready | 0 sales-output-ready scenarios |

Required documents not found:

- `docs/EVIDENCE_REFERENCE_POLICY.md`
- `docs/SOURCE_FRESHNESS_POLICY.md`
- `docs/PRICE_SOURCE_POLICY.md`
- `docs/SALES_OUTPUT_ARCHITECTURE.md`
- `docs/SALES_OUTPUT_ELIGIBILITY.md`

The model-review audit schema is at migration `0012`. Historical project-state/task documents
may still describe the older Week 9/10 state.

Quality checks:

- Ruff format: passed, 277 files formatted at the latest complete check.
- Ruff check: passed.
- Mypy: passed, 239 source and script files checked.
- Full non-network suite with PostgreSQL enabled: 102 passed, 0 skipped; coverage 72%, below the 85% target.
- Migration guard regression: 2 passed, including refusal to drop nonempty audit tables.
- Fresh PostgreSQL migration through `0012`, `downgrade -1`/upgrade, downgrade to base/reupgrade: passed on an isolated database.
- PostgreSQL-only integration tests: 6 passed against `cloud_expert_r011_week11_audit`.
- Historical R011 PostgreSQL evidence remains GO: PostgreSQL 16.14 and 6 integration tests passed.
