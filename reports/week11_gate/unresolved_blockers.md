# Unresolved Blockers

- `W11-B001-review-import`: reviewed files exist, but no controlled database
  import/audit workflow has applied them.
- `W11-B002-reject-reparse`: 2,089 `reject_reparse` decisions require parser,
  normalization, and downstream regeneration before customer output.
- `W11-B003-human-reviewed-mapping`: human-reviewed mapping candidates: 0.
- `W11-B004-customer-evidence`: customer-eligible Evidence Packages: 0.
- `W11-B005-decision-review`: internally approved DecisionResults: 0;
  `DecisionReview` rows: 0.
- `W11-B006-customer-output-readiness`: customer-eligible decision results: 0.
- `W11-B007-required-docs`: `docs/MAPPING_REVIEW_GUIDE.md` and
  `docs/COMPARISON_REPORT_POLICY.md` are still absent.

Because these are hard gates, Week 11 must stop before sales-output
implementation.
