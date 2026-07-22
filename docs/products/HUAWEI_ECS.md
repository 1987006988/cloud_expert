# Huawei Cloud ECS

## Scope

Week 3 covers Huawei Cloud domestic Elastic Cloud Server (ECS) public sources.
The canonical product record is `huawei_cloud` / `ecs` with domestic market
mode. The official product URL is `https://www.huaweicloud.com/product/ecs.html`
and the documentation entry URL is
`https://support.huaweicloud.com/productdesc-ecs/zh-cn_topic_0013771112.html`.

## Registered Sources

Nine ECS sources are registered:

- Product page.
- Product introduction documentation.
- Product feature documentation.
- Instance type overview.
- T6/general-entry instance specifications.
- H3/Hc2 high-performance instance specifications.
- Region and AZ concept page.
- Quotas and limits page.
- ECS SLA declaration.

See `data/source_registry/domestic/huawei_cloud/ecs/` for source policies and
`docs/reviews/WEEK03_SOURCE_REVIEW.md` for the adoption rationale.

## Parsed Records

Week 3 acceptance output for ECS:

| Metric | Count |
| --- | ---: |
| Product records | 1 |
| SKU records | 37 |
| Product family records | 17 |
| Service tier records | 0 |
| SLA records | 2 |
| Parsing runs | 9 |
| Evidence records | 268 |
| Review items | 7 |
| Missing evidence links | 0 |
| Low-confidence fields | 7 |
| Coverage | 11 of 20 expected fields, 0.55 |

The parser extracts instance family cues, SKU codes, vCPU, memory, bandwidth,
PPS, local-disk notes, virtualization/architecture text where locatable, product
description fields, region evidence, quota/limit evidence, and SLA availability
records.

## Review Notes

All seven open ECS review items are `ecs.instance_family` low-confidence fields.
They remain open because family names can be inferred from headings or SKU code
patterns, and those inferences require human confirmation before use in sales or
competitive output.

ECS region evidence is product-level evidence only. The Week 3 acceptance
database has 0 normalized `Region` rows and 0 normalized `Availability` rows
because the approved ECS region source did not expose a reliably parseable
domestic region availability table. This must not be interpreted as proof that
every instance type or SKU is available in every region.
