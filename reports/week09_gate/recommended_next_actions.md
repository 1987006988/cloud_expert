# Week 9 Recommended Next Actions

Generated at: 2026-07-22T23:46:13+08:00

## Required Before Week 9

1. Finish or formally waive R008 human review governance.
2. Complete Week 7 product mapping and record `WEEK7_GATE=GO`.
3. Complete Week 8 Evidence Package implementation and record `WEEK8_GATE=GO`.
4. Ensure Week 8 provides:
   - Evidence Package generation.
   - Stable EvidenceReference codes.
   - Snapshot locator validation.
   - Source freshness status.
   - Customer output eligibility checks.
   - PostgreSQL and coverage gate evidence.
5. Only after those are complete, rerun Week 9 gate.

## Then Start Week 9

When Week 9 becomes eligible, implement pricing and TCO in this order:

1. Define official pricing source policy and Price SKU dimensions.
2. Add immutable PriceSnapshot ingestion and validation.
3. Model billing modes, tax status, regions, currencies, and tiers.
4. Add pricing scenario and usage profile models.
5. Implement Decimal-only cost line item calculation.
6. Add TCO completeness, freshness, conflict, and evidence validation.
7. Export internal, non-binding TCO reports with full assumptions and missing
   items.

Until then, Week 9 must remain a gate-only activity.
