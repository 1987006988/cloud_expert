# Aliyun ECS Product Notes

Week 5 covers Aliyun Elastic Compute Service in the China public cloud domestic
partition `aliyun_public_cn`.

Registered official source groups:

- Product page and "What is ECS" documentation.
- Instance specification naming and instance family documentation.
- DescribeInstanceTypes API reference page as a structured source reference,
  not an API call.
- Regions and Zones documentation plus DescribeRegions/DescribeZones API
  reference pages as source references.
- ECS service-level agreement page.
- Pricing page registered as disabled/manual-only.

## Parsed Product Facts

| Metric | Value |
| --- | ---: |
| Product records | 1 |
| SKU records | 994 |
| Product family records | 208 |
| Region records | 15 |
| Availability records | 15 |
| Zone records | 62 |
| Zone availability records | 62 |
| SLA records | 2 |
| Evidence records | 7891 |
| Review items | 70 |
| Missing evidence links | 0 |
| Field coverage | 0.7692 |

ECS Zone availability is product-level only. It must not be used as evidence
that every ECS instance type or family is available in every listed Zone.

## Review Notes

Open review items are low-confidence parser candidates, mainly table shape,
instance-family, and Zone-name extraction cases. The rows remain evidence-backed
but are not human-reviewed.

The ECS SLA source captured in Week 5 points to the Aliyun terms page whose page
text includes a 2026-07-01 revision date and 2026-09-01 effective date. Treat
the captured page as official source evidence and review effective-date
semantics before customer-facing use.
