# Amazon EC2

## Scope

Week 4 covers Amazon Elastic Compute Cloud in AWS commercial global partition
`aws`. The canonical product record is `aws` / `ec2` with international market
mode.

Primary official URLs:

- `https://aws.amazon.com/ec2/`
- `https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-types.html`
- `https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html`
- `https://docs.aws.amazon.com/ec2/latest/instancetypes/co.html`
- `https://docs.aws.amazon.com/general/latest/gr/ec2-service.html`
- `https://aws.amazon.com/compute/sla/`

## Registered Sources

Ten EC2 sources are registered. Nine are enabled for Week 4 ingestion and one
pricing page is disabled/manual-only.

Enabled source groups:

- EC2 product page.
- Instance type overview and specification index.
- General purpose instance specification tables.
- Compute optimized instance specification tables.
- Network bandwidth documentation.
- EC2 endpoints and Regions.
- EC2 service quotas documentation.
- AWS Compute SLA.

## Parsed Records

| Metric | Count |
| --- | ---: |
| Product records | 1 |
| SKU records | 678 |
| Product family records | 74 |
| Region records | 34 |
| Availability records | 34 |
| SLA records | 2 |
| Evidence records | 5012 |
| Review items | 1349 |
| Missing evidence links | 0 |
| Partition violations | 0 |
| Coverage | 15 of 23 expected fields, 0.6522 |

The parser extracts instance type codes, family codes, vCPU, memory, processor
text, inferred processor vendor/architecture, baseline and maximum network
bandwidth, EBS bandwidth when table headers expose it, local disk hints, product
description fields, commercial Regions, and SLA availability records.

## Review Notes

Most EC2 review items are low-confidence fields caused by inferred architecture,
accelerator, or best-effort bandwidth normalization. They are retained as audit
candidates and must be reviewed before customer-facing claims.

Region availability is product-level only. It must not be used as SKU-level,
family-level, or feature-level availability.
