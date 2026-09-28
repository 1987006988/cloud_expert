# Recommended Next Actions

1. Complete real human review of `D:\审核文件\week11_2026-09-28\week11_mapping_review.csv`.
2. Complete real human review of `D:\审核文件\week11_2026-09-28\week11_decision_review.csv`.
3. Import both review results through an audited, hash-recorded process and preserve review history.
4. Regenerate Mapping, EvidencePackage, DecisionResult, and customer-eligibility results.
5. Re-run Week 11 Gate until it returns GO without waiving customer-output safeguards.
6. Raise measured test coverage from 72% to the 85% target and update stale project-state/task documents.
7. Retain the passing PostgreSQL validation evidence and repeat it for any later schema change.
8. Only after Week 11 is GO, create the Week 12 implementation plan, schema migration, tests, and rollback plan.

The completed 5,154-row model review is available for internal triage, but does not replace
the human sign-off or grant customer-output eligibility.

Deferred Week 12 implementation sequence:

```text
MarketMode contract
-> ProviderPartition and Country/Geography model
-> Entity market-scope resolution
-> scope propagation and compatibility
-> Mapping/Pricing/TCO/Decision/Sales guards
-> contamination detector
-> PostgreSQL migration validation
-> end-to-end domestic/international acceptance
```

Deferred migration rule: historical records with unproven scope must be `unknown` and routed to
review. URL, language, currency, or directory path must not be used as sole market truth.

Rollback approach after admission: keep migrations additive, preserve all historical rows, downgrade
only the Week 12 revision, and retain generated compatibility assessments as reproducible derived data.
