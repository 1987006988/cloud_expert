# Remediation Plan

## Gate

Do not start Week7 feature work until R001-R008 in `tasks/remediation_backlog.yaml` are complete or explicitly waived by a human owner.

## Priority Order

1. Establish git provenance: create an initial audited baseline commit and tag it as a phase audit snapshot.
2. Repair default DB reproducibility: either rebuild `cloud_expert_dev.sqlite` from current migrations or remove it from default workflows.
3. Rebuild Week6 combined projection so it copies SnapshotRecord, IngestionRun, ParsingRun, ProductFamily, ServiceTier, ProductSLA, CloudPartition, Region, Availability, AvailabilityZone, ZoneAvailability, ReviewItem, and DataQualityIssue where relevant.
4. Preserve `Evidence.snapshot_record_id` during projection and add a validator that checks full SourceDocument/SnapshotRecord/raw manifest chain for normalized rows.
5. Expand Week6 canonical schema/enums and field matrices to match the original Prompt.
6. Strengthen ComparabilityAssessment logic so it records explicit blockers for scope, qualifier, unit, evidence, review status, and market mismatch.
7. Raise coverage above the required threshold and add negative tests around ambiguous units, qualitative network values, service-tier scope, stale evidence, and idempotent new rule versions.
8. Run PostgreSQL migration validation once Docker daemon or another PostgreSQL service is available.
