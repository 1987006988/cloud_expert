# Aliyun OSS Product Notes

Week 5 covers Aliyun Object Storage Service in the China public cloud domestic
partition `aliyun_public_cn`.

Registered official source groups:

- Product page and "What is OSS" documentation.
- OSS overview and storage-class documentation.
- Storage selection guidance.
- Regions/endpoints documentation and DescribeRegions API reference page as a
  source reference, not an API call.
- Access network, lifecycle, versioning, replication, encryption, WORM, and
  static website documentation.
- OSS service-level agreement page.
- Pricing page registered as disabled/manual-only.

## Parsed Product Facts

| Metric | Value |
| --- | ---: |
| Product records | 1 |
| Service tier records | 5 |
| Region records | 19 |
| Availability records | 19 |
| SLA records | 1 |
| Evidence records | 148 |
| Review items | 12 |
| Missing evidence links | 0 |
| Field coverage | 0.8333 |

OSS storage classes are stored as `ServiceTier` rows:

- `standard`
- `infrequent_access`
- `archive`
- `cold_archive`
- `deep_cold_archive`

OSS Region availability is product-level only. It must not be used as evidence
that every storage class, feature, redundancy mode, or bucket option is
available in every listed Region.

## Review Notes

Open review items are low-confidence parser candidates, mainly storage-class
retrieval wording and SLA percentage extraction. The rows remain
evidence-backed but are not human-reviewed.
