# Comparison Report Policy

Comparison reports must be evidence constrained. They may summarize only facts
that are traceable to `SourceDocument`, `Evidence`, and, when applicable,
reviewed mapping, pricing, TCO, and decision records.

## Customer-Eligible Content

A comparison statement may be customer eligible only when:

- the mapping candidate is human reviewed;
- the evidence package is customer eligible;
- rejected or deferred review rows are excluded;
- pricing and TCO inputs are complete for cost claims;
- a `DecisionReview` row records internal approval for decision output;
- all conditions, market scope, region scope, and service-tier scope are stated.

## Internal-Only Content

Machine-generated results, pending-review values, rejected reparse findings,
incomplete TCO rows, and cross-market partial comparisons remain internal-only.
They can be used to guide remediation and reviewer work, but not as customer
claims.

## Scope Handling

Product-level capabilities must not be presented as service-tier facts unless
the source explicitly binds the capability to a tier. Service-tier facts must
not be generalized to a product or region without explicit evidence.

SLA values must come from explicit service commitment terms. Service-credit
thresholds, formulas, examples, and percentage multipliers are not SLA
commitments.
