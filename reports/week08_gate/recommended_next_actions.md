# Week 8 Recommended Next Actions

Generated at: 2026-07-22T23:46:13+08:00

## Required Before Week 8

1. Complete or formally waive R008 human review governance.
2. Reopen Week 7 only after `WEEK7_GATE=GO` can be truthfully recorded.
3. Implement Week 7 product mapping foundations: versioned rule sets,
   deterministic mapping candidates, field comparisons, evidence links,
   review isolation, and idempotency checks.
4. Add and run Week 7 validation commands:
   - `scripts/check_week07_gate.py`
   - `scripts/validate_mapping_rules.py`
   - `scripts/validate_mapping_evidence.py`
   - `scripts/validate_mapping_idempotency.py`
5. Generate Week 7 mapping quality reports and keep automatic candidates
   separate from human-approved mappings.
6. Rerun Week 8 gate only after the above is committed.

## Then Start Week 8

When Week 8 becomes eligible, implement evidence packages in this order:

1. Evidence resolver from mapped entities to Evidence, SourceDocument,
   SnapshotRecord, manifest, raw file, locator, and excerpt.
2. Stable reference code generation that does not expose database IDs.
3. Source freshness and reliability policy configuration.
4. Evidence package models, persistence, and idempotent generation.
5. Markdown/JSON comparison report export with explicit missing, stale,
   conflicting, and pending-review facts.
6. Customer-output eligibility checks.

Until then, Week 8 must remain a gate-only activity.
