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
| `needs_review` | Reserved for future human-review routing. |

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
| `partial` | 66 |
| `not_comparable` | 37 |

