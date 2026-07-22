# Amazon S3

## Scope

Week 4 covers Amazon Simple Storage Service in AWS commercial global partition
`aws`. The canonical product record is `aws` / `s3` with international market
mode.

Primary official URLs:

- `https://aws.amazon.com/s3/`
- `https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html`
- `https://docs.aws.amazon.com/general/latest/gr/s3.html`
- `https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html`
- `https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html`
- `https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html`
- `https://aws.amazon.com/s3/sla/`

## Registered Sources

Fourteen S3 sources are registered. Thirteen are enabled for Week 4 ingestion
and one pricing page is disabled/manual-only.

Enabled source groups:

- S3 product page and User Guide landing page.
- Storage classes.
- Endpoints, Regions, and quotas.
- Multipart upload.
- Versioning.
- Lifecycle management.
- Replication.
- Object Lock.
- SSE-KMS encryption.
- Event notifications.
- Static website hosting.
- S3 SLA.

## Parsed Records

| Metric | Count |
| --- | ---: |
| Product records | 1 |
| Service tier records | 8 |
| Region records | 34 |
| Availability records | 34 |
| SLA records | 1 |
| Evidence records | 711 |
| Review items | 1 |
| Missing evidence links | 0 |
| Partition violations | 0 |
| Coverage | 17 of 23 expected fields, 0.7391 |

The parser extracts storage class names, design durability and availability
percentages, minimum storage duration, retrieval text, minimum billable object
size where present, product capability booleans, product-level commercial
Regions, and SLA availability evidence.

## Review Notes

S3 storage classes are represented as `ServiceTier` records. They are not
provider SKUs. Region availability is product-level only and does not prove
storage-class-specific Region availability.
