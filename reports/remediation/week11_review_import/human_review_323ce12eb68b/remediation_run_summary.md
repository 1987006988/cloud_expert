# Week 11 Review Remediation Run Summary

- Run date: `2026-09-28` (`Asia/Shanghai`)
- Database: `test_outputs/week6_combined_projection.sqlite`
- Review batch: `human_review_323ce12eb68b`
- Review package SHA256: `323ce12eb68bf6650f9fa55b3652f479f18330bb07d7d989e1b152c9d4f37d0f`

## Controlled Review Import

- Imported review rows: `2222`
- Accepted: `23`
- Accepted with conditions: `105`
- Rejected and queued for reparse: `2089`
- Deferred: `5`
- Before/after audit rows: `2222`

The original package is archived in this directory. Database audit tables record the package hash,
review batch, source row, reviewer decision, action status, and before/after snapshots.

## Parser Remediation

- AWS EC2 parser: `week11_aws_review_remediation_v1`
- AWS S3 parser: `week11_aws_review_remediation_v1`
- Alibaba Cloud ECS parser: `2026.08.week11_review_remediation_v1`
- Alibaba Cloud OSS parser: `2026.08.week11_review_remediation_v1`
- Active AWS memory records with missing numeric values: `0`
- Alibaba Cloud zones whose name still equals the zone code: `0`
- Rejected legacy SLA records retained for audit: `2`

## Rebuilt Data Layers

- Normalization examined: `11758`
- Normalized records created: `1391`
- Normalized records updated: `9449`
- Human-rejected records kept isolated: `678`
- Comparability assessments created/updated: `33/83`
- Mapping candidates: `414`
- Mapping evidence links: `1420`
- Evidence packages: `414`
- Evidence packages with missing evidence: `0`
- Current official PriceSKU / PriceSnapshot rows: `1/1`
- TCO results: `6` (`1` complete; aggregate scenario remains partial)
- Latest decision runs: `5`
- Latest decision candidate results: `1230`

Missing official prices remain `NULL` with a `missing_reason`; they are not treated as zero.
Machine-generated decisions remain internal-only until the required human reviews are imported.

## Validation

- Ruff format/check: passed
- Targeted parser, normalization, comparability, decision, and migration tests: `30 passed`
- Normalized evidence: `11563` records, `0` missing links, `0` hash mismatches
- Evidence references: `306`, `0` missing snapshots, `0` duplicate reference codes
- Decision evidence: `2460` stored candidate results, `0` validation errors
- Alembic: `downgrade -1`, `upgrade head`, and current revision `0011` verified on the default database

The complete suite cannot be collected with the current Python `3.11.5` environment because the
repository requires Python `>=3.12` and uses PEP 695 generic syntax. This is an environment mismatch,
not a failing assertion in the remediation tests.

## Week 11 Gate

`WEEK11_GATE=NO-GO`

Remaining blockers:

- `W11-B007-human-reviewed-mapping`
- `W11-B008-customer-evidence`
- `W11-B010-decision-review`
- `W11-B011-customer-decision-output`

The latest Mapping and DecisionResult review files were exported to
`D:\审核文件\week11_2026-09-28`. These blockers must remain open until real reviewer decisions are
completed and imported.
