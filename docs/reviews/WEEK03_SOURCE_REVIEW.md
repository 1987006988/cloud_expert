# Week 3 Source Review: Huawei Cloud ECS and OBS

Review date: 2026-07-21

Scope: Huawei Cloud China-site public sources only. Products in scope are ECS
and OBS. International URLs, third-party mirrors, search-result cache pages,
community Q&A, pages requiring authentication, and pricing extraction are out of
scope.

## Robots And Access Review

- `www.huaweicloud.com/robots.txt` disallows selected paths including
  `/common/`, `/tips/`, `/test/`, `/activity/share/`, `/s/`, `/special/`,
  `/zhishi/`, `/guide/`, `/theme/`, and `/topic/`. Adopted product and SLA URLs
  are under `/product/` or `/declaration/sla/` and are not disallowed.
- `support.huaweicloud.com/robots.txt` disallows query-string URLs and selected
  `/special/`, `/zhishi/`, `/guide/`, `/theme/`, and `/topic/` paths. Adopted
  documentation URLs are stable HTML paths without query strings and are not
  under `/intl/`.
- All adopted sources were publicly reachable in a browser without login. Some
  pages display global navigation with login links, but reading the document
  body does not require authenticated access.
- Automated fetch is allowed only for these registered URLs with explicit domain
  policies. No cookies, account sessions, captcha bypass, browser login, or
  private endpoints are used.

## Adopted ECS Sources

| source_id | Source | Reason | Expected fields | Manual review |
| --- | --- | --- | --- | --- |
| `huawei_cloud_ecs_product_page` | `https://www.huaweicloud.com/product/ecs.html` | Official China-site product page. | Product name, product description, product-level feature text. | No pre-fetch review needed; marketing text cannot become quantitative SKU facts. |
| `huawei_cloud_ecs_documentation_intro` | `https://support.huaweicloud.com/productdesc-ecs/zh-cn_topic_0013771112.html` | Official product introduction document. | Product definition, component overview, operating system reference, documentation URL. | Low risk. |
| `huawei_cloud_ecs_product_features` | `https://support.huaweicloud.com/productdesc-ecs/ecs_01_1003.html` | Official feature documentation. | Feature descriptions and lifecycle references. | Feature support may be region-dependent; extracted fields may require review. |
| `huawei_cloud_ecs_instance_types` | `https://support.huaweicloud.com/productdesc-ecs/zh-cn_topic_0035470096.html` | Official instance type and architecture document. | Family codes, architecture, naming convention, family descriptions. | Family mappings inferred from headings or codes need review. |
| `huawei_cloud_ecs_general_entry_specs` | `https://support.huaweicloud.com/productdesc-ecs/ecs_01_0024.html` | Official T6 specification page with SKU-level tables. | SKU code, vCPU, memory, bandwidth, PPS, local disk notes, processor text. | Complex table parsing may produce low-confidence rows. |
| `huawei_cloud_ecs_high_performance_specs` | `https://support.huaweicloud.com/productdesc-ecs/ecs_01_0043.html` | Official H3/Hc2 specification page with SKU-level tables. | SKU code, vCPU, memory, bandwidth, PPS, local disk fields. | Complex table parsing may produce low-confidence rows. |
| `huawei_cloud_ecs_regions` | `https://support.huaweicloud.com/productdesc-ecs/zh-cn_topic_0186645877.html` | Official region and AZ concept page. | Region/AZ definitions and ECS region evidence. | Product-level region evidence must not imply every SKU is available. |
| `huawei_cloud_ecs_quotas_limits` | `https://support.huaweicloud.com/productdesc-ecs/ecs_01_0004.html` | Official constraints and limits page. | Quotas, limits, account restrictions, region constraints. | Pricing references are ignored. |
| `huawei_cloud_ecs_sla` | `https://www.huaweicloud.com/declaration/sla/ecs.html` | Official China-site ECS SLA. | SLA availability percentages, scope, compensation bands. | SLA records remain separate from product design metrics. |

## Adopted OBS Sources

| source_id | Source | Reason | Expected fields | Manual review |
| --- | --- | --- | --- | --- |
| `huawei_cloud_obs_product_page` | `https://www.huaweicloud.com/product/obs` | Official China-site product page. | Product name, description, feature text. | Marketing text cannot become quantitative service facts. |
| `huawei_cloud_obs_features_page` | `https://www.huaweicloud.com/product/obs/features.html` | Official China-site feature page. | Storage class and product capability mentions. | Product-page claims may require confirmation from support docs. |
| `huawei_cloud_obs_documentation_intro` | `https://support.huaweicloud.com/productdesc-obs/zh-cn_topic_0045829060.html` | Official product introduction document. | Product definition, architecture, bucket/object relation, region cues. | Low risk. |
| `huawei_cloud_obs_product_features` | `https://support.huaweicloud.com/productdesc-obs/obs_03_0151.html` | Official feature documentation. | API, bucket/object management, lifecycle, versioning, replication, encryption, static website, event notification cues. | Feature support can be region-dependent. |
| `huawei_cloud_obs_storage_classes` | `https://support.huaweicloud.com/usermanual-obs/obs_41_0080.html` | Official storage-class guide with storage class comparison. | Storage classes, access pattern, minimum duration, retrieval time, design durability, design availability. | Durability, availability, and SLA must be kept separate. |
| `huawei_cloud_obs_constraints_limits` | `https://support.huaweicloud.com/productdesc-obs/obs_03_0360.html` | Official constraints and limits page. | Bandwidth, QPS, resource package scope, URL access rules, object limits. | Pricing references are ignored. |
| `huawei_cloud_obs_regions` | `https://support.huaweicloud.com/productdesc-obs/obs_03_0148.html` | Official region and AZ concept page. | Region/AZ definitions and OBS region evidence. | Product-level region evidence must not imply every storage class is available. |
| `huawei_cloud_obs_lifecycle` | `https://support.huaweicloud.com/usermanual-obs/obs_03_0335.html` | Official lifecycle-management guide. | Lifecycle support and transition/delete capabilities. | Rule limits may need review if extracted. |
| `huawei_cloud_obs_versioning` | `https://support.huaweicloud.com/usermanual-obs/zh-cn_topic_0045829098.html` | Official versioning guide. | Versioning support evidence and constraints. | Low-confidence feature detection enters review. |
| `huawei_cloud_obs_cross_region_replication` | `https://support.huaweicloud.com/usermanual-obs/obs_10_1001.html` | Official cross-region replication guide. | Replication support, scope, constraints. | Does not imply region availability or RPO/SLA. |
| `huawei_cloud_obs_server_side_encryption` | `https://support.huaweicloud.com/usermanual-obs/obs_03_0088.html` | Official server-side encryption guide. | Encryption support, SSE modes, KMS-related evidence. | Customer-managed key support requires exact source wording. |
| `huawei_cloud_obs_sla` | `https://www.huaweicloud.com/declaration/sla/obs.html` | Official China-site OBS SLA. | SLA availability commitments by storage class and AZ scope. | SLA values remain separate from design availability/durability. |

## Rejected Or Deferred Candidates

| Candidate | Decision | Reason |
| --- | --- | --- |
| `https://support.huaweicloud.com/intl/...` ECS and OBS pages | Rejected | International-site path is out of Week 3 scope even when content is in Chinese. |
| Search engine snippets and cached result pages | Rejected | Search results are discovery aids only and cannot be primary evidence. |
| Community pages under `bbs.huaweicloud.com` | Rejected | Community Q&A is not an official primary product fact source. |
| Console pages under `console.huaweicloud.com` | Rejected | Console pages may require account context, login, cookies, and customer-specific data. |
| Pricing pages and pricing calculators | Deferred | Sources may be registered in a later pricing phase, but Week 3 does not parse real pricing. |
| API pages that require broad crawling to discover all endpoints | Deferred | Week 3 focuses on product, specification, region, SLA, and core feature sources. |

## Risks

- Official HTML structure may change without URL changes. Parsers must emit
  low-confidence fields or review items instead of guessing.
- Product pages contain marketing prose. Quantitative product facts should come
  from documentation or SLA pages, not slogans.
- Support pages can contain global navigation and international-site prompts.
  The canonical registered URLs remain China-site paths; `/intl/` URLs are not
  used.
- Region pages define concepts and product-level availability evidence. They do
  not prove every SKU or every OBS storage class is available in every region.
- OBS design durability/availability values are product design metrics. SLA
  commitments are recorded separately in `ProductSLA`.
