# Huawei Cloud OBS

## Scope

Week 3 covers Huawei Cloud domestic Object Storage Service (OBS) public sources.
The canonical product record is `huawei_cloud` / `obs` with domestic market
mode. The official product URL is `https://www.huaweicloud.com/product/obs` and
the documentation entry URL is
`https://support.huaweicloud.com/productdesc-obs/zh-cn_topic_0045829060.html`.

## Registered Sources

Twelve OBS sources are registered:

- Product page.
- Product features page.
- Product introduction documentation.
- Product feature documentation.
- Storage class documentation.
- Constraints and limits documentation.
- Region and AZ concept page.
- Lifecycle management guide.
- Versioning guide.
- Cross-region replication guide.
- Server-side encryption guide.
- OBS SLA declaration.

See `data/source_registry/domestic/huawei_cloud/obs/` for source policies and
`docs/reviews/WEEK03_SOURCE_REVIEW.md` for the adoption rationale.

## Parsed Records

Week 3 acceptance output for OBS:

| Metric | Count |
| --- | ---: |
| Product records | 1 |
| SKU records | 0 |
| Product family records | 0 |
| Service tier records | 4 |
| SLA records | 5 |
| Parsing runs | 12 |
| Evidence records | 83 |
| Review items | 2 |
| Missing evidence links | 0 |
| Low-confidence fields | 2 |
| Coverage | 16 of 19 expected fields, 0.8421 |

The parser extracts storage class records, minimum storage duration,
availability/durability design metrics where present, retrieval descriptions,
product capabilities, region evidence, and SLA records. OBS storage classes are
modeled as `ServiceTier` records, not SKUs.

## Review Notes

Both open OBS review items are low-confidence
`object_storage.retrieval_time_description` fields. Retrieval wording can vary
by storage class and source section, so these remain pending human review.

OBS SLA commitments are stored in `ProductSLA`. They are intentionally separate
from design availability and durability percentages found in storage-class
documentation.

The Week 3 acceptance database has 0 normalized `Region` rows and 0 normalized
`Availability` rows. Current OBS region material is retained as product-level
evidence only; storage-class-by-region availability is not inferred.
