# Huawei Cloud Provider Notes

## Scope

Week 3 registers and parses public Huawei Cloud China-site sources for ECS and
OBS only. Registered URLs use `www.huaweicloud.com` and
`support.huaweicloud.com`. International paths, competitor sites, customer
console pages, community sources, pricing calculators, login-only pages,
account-specific data, and private documents are out of scope.

## Source Registration

Registered official sources:

| Product | Source count | Registry path |
| --- | ---: | --- |
| ECS | 9 | `data/source_registry/domestic/huawei_cloud/ecs/` |
| OBS | 12 | `data/source_registry/domestic/huawei_cloud/obs/` |

The source review is recorded in `docs/reviews/WEEK03_SOURCE_REVIEW.md`.
Robots review found the adopted `/product/`, `/declaration/sla/`, and stable
support-document HTML paths acceptable for this controlled source set. Query
string URLs, `/intl/` paths, search snippets, community pages, and console URLs
were rejected or deferred.

## Evidence Rules

- A real product fact must trace to `SourceDocument`, `SnapshotRecord`, and
  `Evidence`.
- Parsers read stored snapshots only; they do not perform HTTP requests.
- Evidence excerpts are short and locatable with URL, page title, section,
  locator, parser rule, snapshot id, and content hash.
- Low-confidence parsed fields create `ReviewItem` rows.
- SLA facts are stored as `ProductSLA` records, not as design availability or
  generic product claims.
- Pricing references in source pages are ignored in Week 3.

## Current Acceptance Snapshot

The Week 3 acceptance database used
`test_outputs/week3_huawei_acceptance.sqlite`.

| Metric | Count |
| --- | ---: |
| Providers | 1 |
| Products | 2 |
| Source documents | 21 |
| Snapshot records | 21 |
| Ingestion runs | 21 |
| Parsing runs | 21 |
| Evidence records | 351 |
| Parsed field candidates | 390 |
| Product specifications | 228 |
| Review items | 9 |
| Data quality issues | 0 |

Open review items mean the data is usable for internal analysis and parser
iteration, but not yet approved for customer-facing competitive claims.
