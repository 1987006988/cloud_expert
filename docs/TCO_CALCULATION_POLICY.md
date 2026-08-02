# TCO Calculation Policy

TCO calculations use public, evidence-backed price snapshots and explicit
usage assumptions.

Rules:

- amounts use Decimal precision;
- missing line items keep `amount=NULL` and must include `missing_reason`;
- missing line items are not treated as zero;
- completeness is stored separately from total;
- complete, partial, missing-price, and requires-review states are distinct;
- lower TCO does not mean overall best fit.
