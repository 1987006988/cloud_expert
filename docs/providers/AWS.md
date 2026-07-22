# AWS Provider Notes

## Scope

Week 4 registers and parses public AWS commercial global sources for Amazon EC2
and Amazon S3 only. The provider code is `aws`, market mode is
`international`, and the cloud partition code is `aws`.

AWS China (`aws-cn`) and AWS GovCloud (`aws-us-gov`) are out of this Week 4
data slice. Region parsers filter `cn-*` and `us-gov-*` rows, and the partition
validator checks that no such Region codes are attached to the commercial
`aws` partition.

## Source Registration

| Product | Total sources | Enabled sources | Disabled sources | Registry path |
| --- | ---: | ---: | ---: | --- |
| EC2 | 10 | 9 | 1 | `data/source_registry/international/aws/ec2/` |
| S3 | 14 | 13 | 1 | `data/source_registry/international/aws/s3/` |

Disabled sources are pricing pages. They are registered for future pricing
review, but automated fetch and parsing are disabled in Week 4.

The source review is recorded in `docs/reviews/WEEK04_SOURCE_REVIEW.md`.

## Evidence Rules

- Product facts must trace to `SourceDocument`, `SnapshotRecord`, and `Evidence`.
- Parsers read stored snapshots only.
- `CloudPartition` records distinguish AWS commercial from other AWS partitions.
- EC2 instance types are `SKU` rows and EC2 families are `ProductFamily` rows.
- S3 storage classes are `ServiceTier` rows, not SKUs.
- EC2 and S3 Region rows create product-level `Availability` only. They do not
  imply every SKU, family, storage class, or feature is available in every
  Region.
- Pricing, TCO, competitive mapping, sales scripts, RAG, frontend, and LLM calls
  remain out of scope.

## Current Acceptance Snapshot

The Week 4 AWS acceptance database used
`test_outputs/week4_aws_acceptance.sqlite`.

| Metric | EC2 | S3 |
| --- | ---: | ---: |
| Product records | 1 | 1 |
| SKU records | 678 | 0 |
| Product family records | 74 | 0 |
| Service tier records | 0 | 8 |
| Region records | 34 | 34 |
| Availability records | 34 | 34 |
| SLA records | 2 | 1 |
| Evidence records | 5012 | 711 |
| Review items | 1349 | 1 |
| Missing evidence links | 0 | 0 |
| Partition violations | 0 | 0 |
| Coverage ratio | 0.6522 | 0.7391 |

Open review items are expected for low-confidence EC2 derived fields and one S3
SLA extraction. They block customer-facing use until reviewed.
