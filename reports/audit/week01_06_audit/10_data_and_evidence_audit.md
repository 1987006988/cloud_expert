# Data And Evidence Audit

## Verdict

**PARTIAL.** Original Week3-5 acceptance databases preserve the evidence chain in samples. Week6 projection does not.

## Source Registry And Snapshot Validation

- All registry: 74 valid, 4 disabled, 0 errors.
- Huawei registry: 21 valid, 0 disabled.
- AWS registry: 24 valid, 2 disabled pricing sources.
- Aliyun registry: 26 valid, 2 disabled pricing sources.
- Raw snapshots: 90 checked, 0 hash/path/header errors.

## Evidence Chain Sampling

- Week3 Huawei ECS/OBS: 10/10 sampled rows passed ProductSpecification -> Evidence -> SourceDocument -> SnapshotRecord.
- Week4 AWS EC2/S3: 10/10 sampled rows passed.
- Week5 Aliyun ECS/OSS: 10/10 sampled rows passed.
- Week6 combined projection: 0/30 sampled rows passed the SnapshotRecord step.

## Evidence Link Validators

- Week5 and Week6 current-schema validators pass with 0 missing evidence links.
- Upgraded Week3/4/5 audit copies pass with 0 missing evidence links.
- Default DB fails due stale schema.
