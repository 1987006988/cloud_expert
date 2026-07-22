# Week 5 Aliyun Source Review

Week 5 adds Aliyun China public cloud (`provider_code=aliyun`,
`market_mode=domestic`, `cloud_partition=aliyun_public_cn`) ECS and OSS sources.
The user prompt superseded the earlier backlog suggestion of Aliyun overseas
mode.

## Adopted ECS Sources

| Source ID | URL | Purpose |
| --- | --- | --- |
| `aliyun_ecs_product_page` | `https://www.aliyun.com/product/ecs` | ECS product page |
| `aliyun_ecs_what_is_ecs` | `https://help.aliyun.com/zh/ecs/user-guide/what-is-ecs` | Product definition |
| `aliyun_ecs_instance_naming` | `https://help.aliyun.com/zh/ecs/user-guide/instance-specification-naming-and-classification` | Instance naming and classification |
| `aliyun_ecs_instance_families` | `https://help.aliyun.com/zh/ecs/user-guide/overview-of-instance-families` | Instance family and type data |
| `aliyun_ecs_describe_instance_types` | `https://help.aliyun.com/zh/ecs/developer-reference/api-ecs-2014-05-26-describeinstancetypes` | API reference source for instance type fields |
| `aliyun_ecs_regions_zones` | `https://help.aliyun.com/zh/ecs/user-guide/regions-and-zones` | Domestic Region and Zone evidence |
| `aliyun_ecs_describe_regions` | `https://help.aliyun.com/zh/ecs/developer-reference/api-ecs-2014-05-26-describeregions` | API reference source for Regions |
| `aliyun_ecs_describe_zones` | `https://help.aliyun.com/zh/ecs/developer-reference/api-ecs-2014-05-26-describezones` | API reference source for Zones |
| `aliyun_ecs_sla` | `https://terms.aliyun.com/legal-agreement/terms/suit_bu1_ali_cloud/suit_bu1_ali_cloud201909241949_62160.html` | ECS SLA evidence |

## Adopted OSS Sources

| Source ID | URL | Purpose |
| --- | --- | --- |
| `aliyun_oss_product_page` | `https://www.aliyun.com/product/oss` | OSS product page |
| `aliyun_oss_what_is_oss` | `https://help.aliyun.com/zh/oss/user-guide/what-is-oss` | Product definition |
| `aliyun_oss_overview` | `https://help.aliyun.com/zh/oss/user-guide/oss-overview` | OSS overview |
| `aliyun_oss_storage_classes` | `https://help.aliyun.com/zh/oss/user-guide/overview-53/` | Storage classes |
| `aliyun_oss_storage_selection` | `https://help.aliyun.com/zh/oss/user-guide/selection-guidance-selection-guidance` | Storage class selection guidance |
| `aliyun_oss_regions` | `https://help.aliyun.com/zh/oss/user-guide/regions-and-endpoints` | Domestic Region and endpoint evidence |
| `aliyun_oss_describe_regions` | `https://help.aliyun.com/zh/oss/developer-reference/describe-regions` | API reference source for Regions |
| `aliyun_oss_access_network` | `https://help.aliyun.com/zh/oss/user-guide/access-and-network-overview` | Access network capabilities |
| `aliyun_oss_lifecycle` | `https://help.aliyun.com/zh/oss/user-guide/overview-54/` | Lifecycle capability |
| `aliyun_oss_versioning` | `https://help.aliyun.com/zh/oss/overview-78/` | Versioning capability |
| `aliyun_oss_replication` | `https://help.aliyun.com/zh/oss/user-guide/cross-region-replication-overview//` | Replication capability |
| `aliyun_oss_encryption` | `https://help.aliyun.com/zh/oss/user-guide/data-encryption/` | Encryption capability |
| `aliyun_oss_worm` | `https://help.aliyun.com/zh/oss/user-guide/oss-retention-policies` | Retention/WORM capability |
| `aliyun_oss_static_website` | `https://help.aliyun.com/zh/oss/user-guide/hosting-static-websites` | Static website capability |
| `aliyun_oss_sla` | `https://terms.aliyun.com/legal-agreement/terms/suit_bu1_ali_cloud/suit_bu1_ali_cloud201803021527_93160.html` | OSS SLA evidence |

## Disabled Sources

| Source ID | URL | Reason |
| --- | --- | --- |
| `aliyun_ecs_pricing` | `https://www.aliyun.com/price/product#/ecs/detail` | Pricing/TCO is out of Week 5 scope |
| `aliyun_oss_pricing` | `https://www.aliyun.com/price/product#/oss/detail` | Pricing/TCO is out of Week 5 scope |

## Rejected Or Deferred

- `alibabacloud.com` international pages: rejected for domestic-mode Week 5.
- Hong Kong, overseas, finance/special partitions, and government cloud:
  excluded from `aliyun_public_cn` parsing.
- Console, account-specific, AccessKey/API calls, cookies, private endpoints,
  calculators, customer portals, blogs, community pages, and third-party
  comparison pages: rejected.
- Huawei-vs-AWS-vs-Aliyun mapping, pricing/TCO, competitive scoring, sales
  scripts, RAG, frontend, LLM calls, and vector search remain out of scope.

## Validation Notes

- Aliyun registry validation: 26 valid sources, 2 disabled pricing sources, 0
  errors.
- Enabled official snapshots captured into immutable raw storage: 24.
- Raw snapshot validation after Week 5: 90 snapshots checked, 0 errors.
- Evidence link validation for Aliyun: 0 missing evidence links.
- Market-scope validation: 26 registry sources, 24 source documents, 19
  domestic Regions, 62 Zones, 0 errors.
- Region/Zone relationship validation: 62 Zones, 62 ZoneAvailability rows, 0
  errors.
