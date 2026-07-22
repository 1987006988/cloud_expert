# Comparability Policy

Comparability assessments are field-level readiness records. They must not be
used as final competitive claims, product mappings, pricing guidance, or sales
arguments.

## Status Values

| Status | Meaning |
| --- | --- |
| `comparable` | Both products have evidence-backed normalized values for the field, unit, qualifier, and scope. |
| `partial` | At least one readiness condition is incomplete, such as one-sided coverage or different market scope. |
| `not_comparable` | Neither side has usable evidence-backed normalized values for the field. |
| `needs_review` | Both sides have values, but a blocker such as pending review, unit mismatch, qualifier mismatch, or scope mismatch requires human review. |

## Blocker Rules

An assessment is not marked `comparable` unless both sides have evidence-backed
normalized values with aligned field, canonical unit set, value qualifier set,
and scope type. The assessment is downgraded when any of these signals is
present:

- Pending-review normalized values.
- Scope mismatch with the canonical default or between products.
- Canonical unit mismatch between products.
- Value qualifier mismatch between products.
- Domestic/international market-scope mismatch.

## Week 6 Boundaries

- Compute assessments are limited to Huawei ECS, AWS EC2, and Aliyun ECS.
- Object storage assessments are limited to Huawei OBS, AWS S3, and Aliyun OSS.
- Domestic and international market scopes are not merged.
- Region, Zone, storage-class, family, and SKU scope differences block final
  customer-facing comparison until reviewed.

## Week 6 Result

The combined projection generated 116 field-level assessments:

| Status | Count |
| --- | ---: |
| `comparable` | 13 |
| `partial` | 64 |
| `not_comparable` | 37 |
| `needs_review` | 2 |
