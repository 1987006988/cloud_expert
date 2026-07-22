# Week06 Audit

## Verdict

**PARTIAL.** The canonical normalization layer exists and produces reproducible counts, but it does not satisfy the full Week6 Prompt.

## Verified Counts

- Canonical field definitions: 38.
- Normalization rules: 40.
- Normalization runs: 1.
- Product specifications examined in projection: 10412.
- Normalized specifications: 10172.
- Comparability assessments: 116.
- Normalized review status: 9404 machine_extracted, 768 pending_review.
- Comparability status: 13 comparable, 66 partial, 37 not_comparable.
- Scope mismatch warnings: 90.

## Product Normalization Counts

| provider/product | specs | normalized | evidence | snapshots | evidence_without_snapshot |
| --- | --- | --- | --- | --- | --- |
| aliyun/ecs | 6281 | 6281 | 6281 | 0 | 6281 |
| aliyun/oss | 30 | 30 | 30 | 0 | 30 |
| aws/ec2 | 3856 | 3616 | 3856 | 0 | 3856 |
| aws/s3 | 17 | 17 | 17 | 0 | 17 |
| huawei_cloud/ecs | 185 | 185 | 185 | 0 | 185 |
| huawei_cloud/obs | 43 | 43 | 43 | 0 | 43 |

## Major Gaps

- Projection DB has 0 `snapshot_record`, 0 `ingestion_run`, 0 `parsing_run`, 0 `product_family`, 0 `service_tier`, 0 `product_sla`, 0 `region`, 0 `availability`, 0 `availability_zone`, and 0 `zone_availability` rows.
- `scripts/build_week6_combined_acceptance.py` copies Evidence with `snapshot_record_id=None`, causing all sampled Week6 projection evidence chains to fail the SnapshotRecord step.
- Field matrices lack required status columns for semantic match, unit match, scope match, qualifier match, evidence status, and comparability status.
- Enums and schema fields are narrower than the Prompt requirement.
- Comparability logic is coverage-based readiness, not a robust comparison blocker system.
