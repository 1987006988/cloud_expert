# Data Dictionary

Legend:

- Source: `synthetic_fixture`, `official_source`, `evidence`, `manual_review`, or `system`.
- Review: whether human review is required before customer-facing use.
- Sensitive: whether the field may contain secrets, customer data, or internal commercial data. Week 1 fields are designed to avoid sensitive data.

## Week 4 AWS Partition Extensions

Week 4 adds the following fields and table for provider partition safety:

- `SourceRegistryEntry.cloud_partition`: optional registry field. For AWS
  commercial global sources it is `aws`. It prevents accidental mixing with
  `aws-cn` or `aws-us-gov`.
- `SourceDocument.cloud_partition`: stored copy of the registry partition for
  each captured official source version.
- `CloudPartition`: normalized provider partition table with `provider_id`,
  `partition_code`, `partition_name`, `market_mode`, `geography_scope`, and
  `is_active`.
- `Region.cloud_partition_id`: optional link from a normalized Region to its
  provider partition.
- `Availability.cloud_partition_id`: optional link from an availability fact to
  its provider partition.
- `Availability.target_type` and `Availability.target_code`: product, SKU,
  family, service tier, or feature scope. Week 4 AWS parsers populate
  product-level availability only.

Positive availability statuses still require evidence. AWS commercial Region
rows must not include `cn-*` or `us-gov-*` codes.

## Week 5 Aliyun Zone Extensions

Week 5 adds the following fields and tables for Aliyun domestic public cloud
Region/Zone safety:

- `AvailabilityZone`: normalized provider Zone table. For Aliyun domestic mode,
  `zone_code` values such as `cn-hangzhou-i` must link to parent Region
  `cn-hangzhou` and partition `aliyun_public_cn`.
- `ZoneAvailability`: product-level Zone availability facts linked to
  `Product`, `Region`, `AvailabilityZone`, `CloudPartition`, and `Evidence`.
- `ProductFamilyType.aliyun_ecs_instance_family`: ECS instance family type for
  Aliyun.
- `ProductFamilyType.aliyun_oss_storage_class`: reserved storage class enum for
  Aliyun OSS; normalized OSS storage classes are currently stored as
  `ServiceTier`.

Positive Zone availability statuses require evidence. Aliyun domestic public
cloud rows must not include China Hong Kong, overseas, government, finance, or
special partition Region/Zone codes.

## Provider

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| code | 厂商稳定代码 | string | yes | synthetic_huawei | manual_review | yes | no | immutable after review |
| name | 厂商内部名称 | string | yes | Synthetic Huawei Provider | manual_review | yes | no | controlled update |
| display_name | 展示名称 | string | yes | Synthetic Huawei | manual_review | yes | no | controlled update |
| provider_type | 厂商类型 | string | yes | fixture | manual_review | yes | no | controlled update |
| official_website | 官方网站 | string URL | no | https://example.invalid/provider | official_source | yes | no | update when source changes |
| is_active | 是否启用 | boolean | yes | true | manual_review | yes | no | soft disable |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## Source Registry YAML

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| source_id | Stable source registry identifier | string | yes | synthetic_html_fixture | manual_review | yes | no | immutable after use |
| provider_code | Provider code from the data model | string | yes | synthetic_provider | manual_review | yes | no | controlled update |
| market_mode | Domestic or international source scope | enum string | yes | domestic | manual_review | yes | no | controlled update |
| product_code | Optional product scope | string | no | synthetic_compute | manual_review | yes | no | controlled update |
| source_type | Document, pricing, API, changelog, or other source type | enum string | yes | documentation | official_source | yes | no | immutable per source |
| url | Canonical source URL | URL | yes | https://synthetic.example.invalid/page | official_source | yes | no | version through new review |
| expected_content_type | Allowed MIME types | list[string] | yes | ["text/html"] | manual_review | yes | no | review before changing |
| domain_policy | Allowed domains and redirect policy | object | yes | {"allowed_domains":["example.invalid"]} | manual_review | yes | no | review before changing |
| fetch_policy | Timeout, retry, rate limit, and max size | object | yes | {"max_retries":2} | system | yes | no | controlled update |
| storage_policy | Raw retention and header storage policy | object | yes | {"keep_all_versions":true} | system | yes | no | keep all versions |
| terms_review_status | Automation terms review status | enum string | yes | approved | manual_review | yes | no | manual review |
| fixture_response_path | Local synthetic fixture response | path | no | data/source_registry/fixtures/responses/synthetic_page.html | synthetic_fixture | no | no | fixture only |

## SnapshotRecord

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| source_document_id | Linked source document version | integer | yes | 1 | system | no | no | immutable |
| source_id | Registry source id | string | yes | synthetic_html_fixture | system | no | no | immutable |
| content_hash | Raw content SHA-256 | string | yes | 64 hex chars | system | no | no | immutable |
| normalized_hash | Future normalized content SHA-256 | string | no | null | system | no | no | immutable when set |
| normalization_version | Normalization algorithm version | string | no | null | system | no | no | controlled update |
| storage_path | Relative raw content path | string | yes | domestic/synthetic_provider/unscoped/.../raw.bin | system | no | no | immutable |
| manifest_path | Relative manifest path | string | yes | domestic/synthetic_provider/unscoped/.../manifest.json | system | no | no | immutable |
| content_type | Response MIME type | string | no | text/html | system | no | no | immutable |
| content_length_bytes | Raw byte length | integer | no | 1024 | system | no | no | immutable |
| captured_at | Capture timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| previous_snapshot_id | Previous snapshot pointer | integer | no | 1 | system | no | no | immutable |
| change_status | Change classification | enum string | yes | first_seen | system | yes | no | append-only |
| is_current | Current snapshot marker | boolean | yes | true | system | no | no | update marker only |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |

## IngestionRun

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| source_id | Registry source id | string | yes | synthetic_html_fixture | system | no | no | immutable |
| run_type | Manual, scheduled, retry, validation, or dry run | enum string | yes | manual | system | no | no | immutable |
| started_at | Run start timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| completed_at | Run completion timestamp | timestamp | no | 2026-07-21T00:00:01Z | system | no | no | immutable |
| status | Run outcome | enum string | yes | succeeded | system | yes | no | immutable |
| requested_url | Initial URL | URL | yes | https://synthetic.example.invalid/page | registry | yes | no | immutable |
| final_url | Final URL after redirects | URL | no | https://synthetic.example.invalid/page | system | yes | no | immutable |
| http_status | HTTP status code | integer | no | 200 | system | no | no | immutable |
| content_type | MIME type | string | no | text/html | system | no | no | immutable |
| bytes_downloaded | Downloaded byte count | integer | no | 1024 | system | no | no | immutable |
| retry_count | Retry attempts used | integer | yes | 0 | system | no | no | immutable |
| duration_ms | Duration in milliseconds | integer | no | 50 | system | no | no | immutable |
| snapshot_id | Linked `SnapshotRecord.id` | integer | no | 1 | system | no | no | immutable |
| error_code | Structured failure code | enum string | no | domain_not_allowed | system | yes | no | immutable |
| error_message | Short failure message | text | no | blocked private IP | system | yes | no | inspect before sharing |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |

## ProductCategory

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| code | 统一分类代码 | string | yes | compute | manual_review | yes | no | immutable after review |
| name | 分类名称 | string | yes | Synthetic Compute | manual_review | yes | no | controlled update |
| parent_id | 父分类ID | integer | no | null | manual_review | yes | no | controlled update |
| description | 分类说明 | text | no | Synthetic compute category | manual_review | yes | no | controlled update |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## Product

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| provider_id | 所属厂商 | integer | yes | 1 | manual_review | yes | no | controlled update |
| category_id | 产品分类 | integer | yes | 1 | manual_review | yes | no | controlled update |
| market_mode | 市场模式 | enum string | yes | domestic | manual_review | yes | no | controlled update |
| code | 厂商内产品代码 | string | yes | synthetic_compute_a | evidence | yes | no | immutable after review |
| official_name | 官方名称 | string | yes | Synthetic Compute A | evidence | yes | no | versioned by source |
| display_name | 展示名称 | string | yes | Synthetic Compute A | manual_review | yes | no | controlled update |
| description | 产品说明 | text | no | Synthetic product | evidence | yes | no | versioned by source |
| product_status | 产品状态 | enum string | yes | unknown | evidence | yes | no | update with evidence |
| official_url | 产品页URL | string URL | no | https://example.invalid/products/a | official_source | yes | no | update with source |
| documentation_url | 文档URL | string URL | no | https://example.invalid/docs/a | official_source | yes | no | update with source |
| first_seen_at | 首次发现时间 | timestamp | no | 2026-07-21T00:00:00Z | system | no | no | set once when known |
| last_verified_at | 最近验证时间 | timestamp | no | 2026-07-21T00:00:00Z | evidence | yes | no | update after verification |
| metadata_json | 扩展元数据 | JSON | no | {"fixture": true} | manual_review | yes | no | avoid core facts |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## ProductAlias

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| product_id | 产品ID | integer | yes | 1 | manual_review | yes | no | immutable after review |
| alias | 别名文本 | string | yes | Synthetic Compute Alias | evidence | yes | no | append new alias |
| alias_type | 别名类型 | enum string | yes | english_name | evidence | yes | no | controlled update |
| language | 语言代码 | string | yes | en | evidence | yes | no | use unknown if missing |
| is_official | 是否官方别名 | boolean | yes | false | evidence | yes | no | update with evidence |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |

## SKU

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| product_id | 产品ID | integer | yes | 1 | evidence | yes | no | immutable |
| provider_sku_code | 厂商SKU代码 | string | yes | synthetic-sku-a | evidence | yes | no | immutable after review |
| name | SKU名称 | string | yes | Synthetic SKU A | evidence | yes | no | versioned by source |
| sku_family | SKU系列 | string | no | synthetic-family | evidence | yes | no | update with evidence |
| architecture | 架构 | string | no | unknown | evidence | yes | no | update with evidence |
| operating_system | 操作系统 | string | no | unknown | evidence | yes | no | update with evidence |
| status | SKU状态 | enum string | yes | unknown | evidence | yes | no | update with evidence |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## Region

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| provider_id | 厂商ID | integer | yes | 1 | evidence | yes | no | immutable |
| code | 厂商Region代码 | string | yes | synthetic-cn-1 | evidence | yes | no | immutable after review |
| name | Region名称 | string | yes | Synthetic CN Region 1 | evidence | yes | no | update with evidence |
| country_code | 国家代码 | string | yes | CN | evidence | yes | no | update with evidence |
| geography | 地理区域说明 | string | no | synthetic-geography | evidence | yes | no | update with evidence |
| market_mode | 市场模式 | enum string | yes | domestic | manual_review | yes | no | controlled update |
| is_active | 是否启用 | boolean | yes | true | evidence | yes | no | soft disable |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## Availability

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| product_id | 产品ID | integer | yes | 1 | evidence | yes | no | immutable |
| region_id | Region ID | integer | yes | 1 | evidence | yes | no | immutable |
| availability_status | 可用状态 | enum string | yes | unknown | evidence | yes | no | update with evidence |
| public_preview | 是否公开预览 | boolean | yes | false | evidence | yes | no | update with evidence |
| generally_available | 是否正式可用 | boolean | yes | false | evidence | yes | no | update with evidence |
| available_since | 可用开始时间 | timestamp | no | null | evidence | yes | no | update with evidence |
| unavailable_since | 不可用开始时间 | timestamp | no | null | evidence | yes | no | update with evidence |
| last_verified_at | 最近验证时间 | timestamp | no | 2026-07-21T00:00:00Z | evidence | yes | no | update after verification |
| evidence_id | 证据ID | integer | no | 1 | evidence | yes | no | required for positive status |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## AvailabilityZone

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| provider_id | 厂商ID | integer | yes | 1 | evidence | yes | no | immutable |
| region_id | 父Region ID | integer | yes | 1 | evidence | yes | no | immutable after review |
| cloud_partition_id | 云分区ID | integer | no | 1 | registry/evidence | yes | no | update with reviewed source |
| zone_code | 厂商Zone代码 | string | yes | cn-hangzhou-i | evidence | yes | no | immutable after review |
| zone_name | Zone名称 | string | yes | 杭州 可用区 I | evidence | yes | no | update with evidence |
| market_mode | 市场模式 | enum string | yes | domestic | registry | yes | no | controlled update |
| is_active | 是否启用 | boolean | yes | true | evidence | yes | no | soft disable |
| evidence_id | 证据ID | integer | no | 1 | evidence | yes | no | required for reviewed Zone |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## ZoneAvailability

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| product_id | 产品ID | integer | yes | 1 | evidence | yes | no | immutable |
| region_id | Region ID | integer | yes | 1 | evidence | yes | no | immutable |
| availability_zone_id | Zone ID | integer | yes | 1 | evidence | yes | no | immutable |
| cloud_partition_id | 云分区ID | integer | no | 1 | registry/evidence | yes | no | update with reviewed source |
| target_type | 可用性目标类型 | string | yes | product | parser | yes | no | controlled update |
| target_code | 可用性目标代码 | string | yes | ecs | parser | yes | no | controlled update |
| availability_status | 可用状态 | enum string | yes | available | evidence | yes | no | update with evidence |
| public_preview | 是否公开预览 | boolean | yes | false | evidence | yes | no | update with evidence |
| generally_available | 是否正式可用 | boolean | yes | true | evidence | yes | no | update with evidence |
| available_since | 可用开始时间 | timestamp | no | null | evidence | yes | no | update with evidence |
| unavailable_since | 不可用开始时间 | timestamp | no | null | evidence | yes | no | update with evidence |
| last_verified_at | 最近验证时间 | timestamp | no | 2026-07-21T00:00:00Z | evidence | yes | no | update after verification |
| evidence_id | 证据ID | integer | no | 1 | evidence | yes | no | required for positive status |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## SourceDocument

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| provider_id | 厂商ID | integer | yes | 1 | manual_review | yes | no | immutable |
| source_type | 来源类型 | enum string | yes | documentation | official_source | yes | no | immutable per version |
| title | 来源标题 | string | yes | Synthetic fixture source | official_source | yes | no | immutable per version |
| url | 来源URL | string URL | yes | https://example.invalid/source | official_source | yes | no | immutable per version |
| language | 语言 | string | no | en | official_source | yes | no | immutable per version |
| authority_level | 权威等级 | enum string | yes | unknown | manual_review | yes | no | controlled update |
| published_at | 发布时间 | timestamp | no | null | official_source | yes | no | immutable per version |
| captured_at | 捕获时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| content_hash | 内容哈希 | string | yes | synthetic-content-hash-001 | system | no | no | immutable |
| storage_path | 原始快照路径 | string | no | snapshots/synthetic.html | system | no | no | immutable per version |
| mime_type | MIME类型 | string | no | text/html | system | no | no | immutable per version |
| http_status | HTTP状态码 | integer | no | 200 | system | no | no | immutable per version |
| is_current | 是否当前版本 | boolean | yes | true | manual_review | yes | no | mark current only |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |

## Evidence

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| source_document_id | 来源文档ID | integer | yes | 1 | evidence | yes | no | immutable |
| section_title | 章节标题 | string | no | Synthetic section | evidence | yes | no | controlled update |
| locator | 定位信息 | string | yes | html:#synthetic | evidence | yes | no | controlled update |
| excerpt | 必要摘录 | text | yes | Synthetic excerpt | evidence | yes | no | keep minimal |
| evidence_type | 证据类型 | enum string | yes | html_section | evidence | yes | no | controlled update |
| confidence | 置信度 | float 0..1 | yes | 0.75 | evidence | yes | no | update on review |
| review_status | 审核状态 | enum string | yes | pending_review | manual_review | yes | no | review workflow |
| reviewed_by | 审核人标识 | string | no | reviewer-id | manual_review | yes | no | avoid personal secrets |
| reviewed_at | 审核时间 | timestamp | no | 2026-07-21T00:00:00Z | manual_review | yes | no | set on review |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## SpecificationDefinition

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| code | 参数代码 | string | yes | synthetic_vcpu_count | manual_review | yes | no | immutable after review |
| name | 参数名称 | string | yes | Synthetic vCPU Count | manual_review | yes | no | controlled update |
| category_id | 分类ID | integer | yes | 1 | manual_review | yes | no | controlled update |
| data_type | 数据类型 | enum string | yes | numeric | manual_review | yes | no | immutable after use |
| canonical_unit | 标准单位 | string | no | count | manual_review | yes | no | controlled update |
| description | 参数说明 | text | no | Synthetic parameter | manual_review | yes | no | controlled update |
| is_required | 是否必填 | boolean | yes | false | manual_review | yes | no | controlled update |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## ProductSpecification

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| product_id | 产品ID | integer | yes | 1 | evidence | yes | no | immutable |
| sku_id | SKU ID | integer | no | 1 | evidence | yes | no | immutable per row |
| definition_id | 参数定义ID | integer | yes | 1 | manual_review | yes | no | immutable |
| numeric_value | 数值型值 | decimal | conditional | 2 | evidence | yes | no | append version |
| text_value | 文本型值 | text | conditional | synthetic | evidence | yes | no | append version |
| boolean_value | 布尔型值 | boolean | conditional | true | evidence | yes | no | append version |
| raw_value | 原始值 | text | yes | synthetic 2 | evidence | yes | no | immutable |
| raw_unit | 原始单位 | string | no | count | evidence | yes | no | immutable |
| canonical_value | 标准化值 | string | no | 2 | evidence | yes | no | controlled update |
| canonical_unit | 标准化单位 | string | no | count | manual_review | yes | no | controlled update |
| evidence_id | 证据ID | integer | yes | 1 | evidence | yes | no | immutable |
| valid_from | 生效开始 | timestamp | no | null | evidence | yes | no | append version |
| valid_to | 生效结束 | timestamp | no | null | evidence | yes | no | expire old row |
| last_verified_at | 最近验证时间 | timestamp | no | null | evidence | yes | no | update after verification |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## PriceSKU

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| provider_id | 厂商ID | integer | yes | 1 | evidence | yes | no | immutable |
| product_id | 产品ID | integer | yes | 1 | evidence | yes | no | immutable |
| sku_id | SKU ID | integer | no | 1 | evidence | yes | no | immutable |
| region_id | Region ID | integer | yes | 1 | evidence | yes | no | immutable |
| provider_price_code | 厂商价格项代码 | string | yes | synthetic-price-a | evidence | yes | no | immutable after review |
| charge_category | 计费类别 | enum string | yes | compute | evidence | yes | no | controlled update |
| billing_mode | 计费模式 | enum string | yes | on_demand | evidence | yes | no | controlled update |
| billing_unit | 计费单位 | string | yes | synthetic-hour | evidence | yes | no | controlled update |
| currency | 币种 | string | yes | USD | evidence | yes | no | update with source |
| tax_included | 是否含税 | boolean | yes | false | evidence | yes | no | update with source |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## PriceSnapshot

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| price_sku_id | 价格项ID | integer | yes | 1 | evidence | yes | no | immutable |
| unit_price | 单价 | decimal | yes | 0.12340000 | evidence | yes | no | append-only |
| minimum_quantity | 最小数量 | decimal | no | 0 | evidence | yes | no | append-only |
| maximum_quantity | 最大数量 | decimal | no | null | evidence | yes | no | append-only |
| billing_period | 计费周期 | string | no | synthetic-hour | evidence | yes | no | append-only |
| discount_type | 折扣类型 | enum string | yes | list | evidence | yes | no | append-only |
| captured_at | 捕获时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| effective_from | 生效开始 | timestamp | no | null | evidence | yes | no | append-only |
| effective_to | 生效结束 | timestamp | no | null | evidence | yes | no | append-only |
| evidence_id | 证据ID | integer | yes | 1 | evidence | yes | no | immutable |
| source_payload_path | 原始载荷路径 | string | no | tests/fixtures/synthetic_price_payload.json | system | no | no | immutable |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |

## ProductMapping

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| source_product_id | 源产品ID | integer | yes | 1 | manual_review | yes | no | immutable |
| target_product_id | 目标产品ID | integer | yes | 2 | manual_review | yes | no | immutable |
| source_sku_id | 源SKU ID | integer | no | 1 | manual_review | yes | no | immutable |
| target_sku_id | 目标SKU ID | integer | no | null | manual_review | yes | no | immutable |
| mapping_level | 映射层级 | enum string | yes | product | manual_review | yes | no | controlled update |
| mapping_status | 映射状态 | enum string | yes | pending_review | manual_review | yes | no | review workflow |
| scenario_code | 场景代码 | string | yes | synthetic_scenario | manual_review | yes | no | controlled update |
| rationale | 映射理由 | text | no | Synthetic mapping | manual_review | yes | no | controlled update |
| evidence_id | 证据ID | integer | no | 1 | evidence | yes | no | update with review |
| review_status | 审核状态 | enum string | yes | pending_review | manual_review | yes | no | review workflow |
| reviewed_at | 审核时间 | timestamp | no | null | manual_review | yes | no | set on review |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## CompetitiveClaim

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| market_mode | 市场模式 | enum string | yes | domestic | manual_review | yes | no | controlled update |
| source_product_id | 源产品ID | integer | yes | 1 | manual_review | yes | no | immutable |
| target_product_id | 目标产品ID | integer | yes | 2 | manual_review | yes | no | immutable |
| scenario_code | 场景代码 | string | yes | synthetic_claim_scenario | manual_review | yes | no | controlled update |
| claim_type | 结论类型 | enum string | yes | neutral_difference | manual_review | yes | no | controlled update |
| claim_text | 结论文本 | text | yes | Synthetic claim | manual_review | yes | no | evidence-backed update |
| customer_value | 客户价值 | text | no | Synthetic value | manual_review | yes | no | evidence-backed update |
| applicable_conditions | 适用条件 | text | yes | Synthetic conditions | manual_review | yes | no | evidence-backed update |
| limitations | 限制条件 | text | yes | Synthetic limitations | manual_review | yes | no | evidence-backed update |
| evidence_id | 证据ID | integer | yes | 1 | evidence | yes | no | immutable |
| confidence | 置信度 | float 0..1 | yes | 0.5 | manual_review | yes | no | review workflow |
| review_status | 审核状态 | enum string | yes | pending_review | manual_review | yes | no | review workflow |
| valid_from | 生效开始 | timestamp | no | null | manual_review | yes | no | controlled update |
| valid_to | 生效结束 | timestamp | no | null | manual_review | yes | no | expire claim |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## SalesScenario

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| code | 场景代码 | string | yes | overseas_ecommerce | synthetic_fixture | yes | no | controlled update |
| name | 场景名称 | string | yes | Synthetic Overseas Ecommerce | synthetic_fixture | yes | no | controlled update |
| market_mode | 市场模式 | enum string | yes | international | synthetic_fixture | yes | no | controlled update |
| industry | 行业 | string | no | ecommerce | synthetic_fixture | yes | no | controlled update |
| country_code | 国家代码 | string | no | SG | synthetic_fixture | yes | no | controlled update |
| description | 场景说明 | text | no | Synthetic scenario | synthetic_fixture | yes | no | controlled update |
| default_weights_json | 默认权重 | JSON | no | {"price": 0.3} | synthetic_fixture | yes | no | controlled update |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## EvaluationCase

| Field | 中文含义 | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | 数据库主键 | integer | yes | 1 | system | no | no | immutable |
| case_code | 评测用例代码 | string | yes | synthetic_mapping_case | synthetic_fixture | yes | no | controlled update |
| case_type | 用例类型 | enum string | yes | product_mapping | synthetic_fixture | yes | no | controlled update |
| input_payload | 输入载荷 | JSON | yes | {"fixture": true} | synthetic_fixture | yes | no | avoid real customer data |
| expected_behavior | 期望行为 | text | yes | Require evidence | synthetic_fixture | yes | no | controlled update |
| expected_sources | 期望来源 | JSON | no | ["example.invalid"] | synthetic_fixture | yes | no | controlled update |
| risk_level | 风险等级 | string | yes | low | synthetic_fixture | yes | no | controlled update |
| is_active | 是否启用 | boolean | yes | true | manual_review | yes | no | soft disable |
| created_at | 创建时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | 更新时间 | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## Week 3 Evidence Extensions

The `Evidence` table now includes extra provenance fields for parsed official
source facts.

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| page_title | Source page title at parse time | string | no | Elastic Cloud Server | evidence | yes | no | immutable per evidence row |
| snapshot_record_id | Raw snapshot used by the parser | integer | no | 1 | system | no | no | immutable |
| content_hash | Raw snapshot SHA-256 hash | string | no | 64 hex chars | system | no | no | immutable |
| parser_rule | Parser rule that emitted the field | string | no | ecs_specs_table_v1 | parser | yes | no | immutable per parser version |

## Week 3 Product Extension Tables

These tables support Huawei Cloud ECS and OBS parsing while preserving the
evidence-first rules from Week 1 and Week 2.

### ProductFamily

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| provider_id | Provider id | integer | yes | 1 | evidence | yes | no | immutable |
| product_id | Product id | integer | yes | 1 | evidence | yes | no | immutable |
| family_code | Provider family code | string | yes | s6 | evidence | yes | no | evidence-backed update |
| family_name | Family display name | string | yes | General computing | evidence | yes | no | evidence-backed update |
| architecture | Architecture or processor family text | string | no | x86 | evidence | yes | no | review if inferred |
| generation | Generation text | string | no | sixth generation | evidence | yes | no | review if inferred |
| description | Family description | text | no | compute family description | evidence | yes | no | evidence-backed update |
| evidence_id | Supporting evidence id | integer | yes | 1 | evidence | yes | no | immutable per version |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | Row update timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

### ServiceTier

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| provider_id | Provider id | integer | yes | 1 | evidence | yes | no | immutable |
| product_id | Product id | integer | yes | 1 | evidence | yes | no | immutable |
| tier_code | Provider tier code | string | yes | standard | evidence | yes | no | evidence-backed update |
| tier_name | Tier display name | string | yes | Standard storage | evidence | yes | no | evidence-backed update |
| tier_type | Tier type | enum string | yes | storage_class | evidence | yes | no | controlled update |
| access_pattern | Access pattern text | text | no | frequent access | evidence | yes | no | review before customer use |
| min_storage_duration_days | Minimum storage duration | integer | no | 30 | evidence | yes | no | evidence-backed update |
| retrieval_time_description | Retrieval time text | text | no | immediate | evidence | yes | no | review if low confidence |
| evidence_id | Supporting evidence id | integer | yes | 1 | evidence | yes | no | immutable per version |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | Row update timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

### ProductSLA

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| provider_id | Provider id | integer | yes | 1 | evidence | yes | no | immutable |
| product_id | Product id | integer | yes | 1 | evidence | yes | no | immutable |
| service_tier_id | Optional service tier id | integer | no | 1 | evidence | yes | no | immutable |
| sla_code | Stable SLA code | string | yes | obs_standard_availability | evidence | yes | no | evidence-backed update |
| record_type | SLA record type | enum string | yes | availability | evidence | yes | no | immutable per record |
| commitment_value | Normalized commitment value | decimal | no | 99.95 | evidence | yes | no | evidence-backed update |
| commitment_unit | Commitment unit | string | no | percent | evidence | yes | no | controlled update |
| scope | Applicability scope | text | no | single-AZ standard storage | evidence | yes | no | review before customer use |
| compensation | Compensation or exclusion text | text | no | service credit policy | evidence | yes | no | review before customer use |
| evidence_id | Supporting evidence id | integer | yes | 1 | evidence | yes | no | immutable per version |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | Row update timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## Week 3 Parsing And Review Tables

### ParsingRun

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| provider_code | Provider code | string | yes | huawei_cloud | system | no | no | immutable |
| product_code | Product code | string | yes | ecs | system | no | no | immutable |
| source_id | Source registry id | string | yes | huawei_cloud_ecs_sla | system | no | no | immutable |
| snapshot_record_id | Snapshot used for parsing | integer | yes | 1 | system | no | no | immutable |
| parser_name | Parser name | string | yes | huawei_ecs_parser | system | yes | no | version through parser release |
| parser_version | Parser version | string | yes | 2026.07.week03 | system | yes | no | immutable per run |
| started_at | Parse start timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| completed_at | Parse completion timestamp | timestamp | no | 2026-07-21T00:00:02Z | system | no | no | immutable |
| status | Run status | enum string | yes | succeeded | system | yes | no | immutable |
| fields_found | Number of candidates emitted | integer | yes | 20 | system | no | no | immutable |
| fields_persisted | Number of normalized facts persisted | integer | yes | 18 | system | no | no | immutable |
| review_items_created | Review item count | integer | yes | 2 | system | yes | no | immutable |
| error_message | Parse error summary | text | no | unsupported table shape | system | yes | no | inspect before sharing |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |

### ParsedFieldCandidate

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| parsing_run_id | Parse run id | integer | yes | 1 | system | no | no | immutable |
| field_code | Canonical field code | string | yes | ecs.vcpu_count | parser | yes | no | controlled by parser |
| raw_value | Source value text | text | yes | 2 vCPUs | evidence | yes | no | immutable |
| normalized_value | Normalized value text | text | no | 2 | parser | yes | no | immutable per parser version |
| canonical_value | Canonical comparable value | text | no | 2 | parser | yes | no | immutable per parser version |
| canonical_unit | Canonical unit | string | no | count | parser | yes | no | controlled update |
| target_table | Intended target table | string | yes | product_specification | parser | yes | no | immutable |
| target_identity | Natural key for target row | JSON | yes | {"sku":"t6.small.1"} | parser | yes | no | immutable |
| locator | Source locator | string | yes | table:1,row:3,col:vCPU | evidence | yes | no | immutable |
| excerpt | Short evidence excerpt | text | yes | source table row text | evidence | yes | no | keep minimal |
| confidence | Parser confidence | float | yes | 0.90 | parser | yes | no | immutable per run |
| review_status | Candidate review status | enum string | yes | pending_review | manual_review | yes | no | review workflow |
| parser_rule | Parser rule id | string | yes | ecs_specs_table_v1 | parser | yes | no | immutable per parser version |
| evidence_id | Supporting evidence id | integer | no | 1 | evidence | yes | no | set when evidence is persisted |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |

### ReviewItem

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| item_type | Review item type | enum string | yes | low_confidence_field | system | yes | no | immutable |
| severity | Severity | enum string | yes | medium | system | yes | no | controlled update |
| status | Review workflow status | enum string | yes | open | manual_review | yes | no | review workflow |
| provider_code | Provider code | string | yes | huawei_cloud | system | no | no | immutable |
| product_code | Product code | string | yes | obs | system | no | no | immutable |
| source_id | Source registry id | string | no | huawei_cloud_obs_storage_classes | system | no | no | immutable |
| field_code | Affected field code | string | no | object_storage.retrieval_time_description | parser | yes | no | immutable |
| target_table | Affected table | string | no | service_tier | parser | yes | no | immutable |
| target_identity | Affected natural key | JSON | no | {"tier":"archive"} | parser | yes | no | immutable |
| evidence_id | Supporting evidence id | integer | no | 1 | evidence | yes | no | immutable |
| reason | Review reason | text | yes | below confidence threshold | system | yes | no | controlled update |
| resolution_notes | Human resolution notes | text | no | approved after source check | manual_review | yes | no | append |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | Row update timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

### DataQualityIssue

| Field | Meaning | Type | Required | Example | Source | Review | Sensitive | Update Strategy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| id | Database primary key | integer | yes | 1 | system | no | no | immutable |
| issue_type | Issue code | string | yes | missing_evidence | system | yes | no | immutable |
| severity | Severity | enum string | yes | high | system | yes | no | controlled update |
| provider_code | Provider code | string | yes | huawei_cloud | system | no | no | immutable |
| product_code | Product code | string | no | ecs | system | no | no | immutable |
| source_id | Source registry id | string | no | huawei_cloud_ecs_sla | system | no | no | immutable |
| target_table | Affected table | string | no | product_sla | system | yes | no | immutable |
| target_identity | Affected natural key | JSON | no | {"sla_code":"ecs_availability"} | system | yes | no | immutable |
| description | Issue description | text | yes | normalized row missing evidence | system | yes | no | controlled update |
| evidence_id | Optional related evidence id | integer | no | 1 | evidence | yes | no | immutable |
| status | Issue status | string | yes | open | manual_review | yes | no | review workflow |
| created_at | Row creation timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | immutable |
| updated_at | Row update timestamp | timestamp | yes | 2026-07-21T00:00:00Z | system | no | no | automatic |

## Week 6 Canonical Normalization Tables

Week 6 adds derived canonical tables. They do not overwrite
`ProductSpecification` or `Evidence`.

| Table | Purpose | Key fields |
| --- | --- | --- |
| `canonical_field_definition` | Stable cross-provider field registry | `code`, `domain`, `data_type`, `canonical_unit`, `default_qualifier`, `default_scope_type` |
| `normalization_rule` | Versioned legacy-field to canonical-field mapping | `code`, `version`, `source_field_code`, `canonical_field_id`, `value_qualifier`, `scope_type` |
| `normalization_run` | Audit and rollback boundary for one derived run | `run_key`, `status`, `records_examined`, `records_created`, `records_skipped` |
| `normalized_specification` | Derived canonical value linked to source evidence | `product_specification_id`, `canonical_field_id`, `evidence_id`, `scope_type`, `value_qualifier`, `quality_score` |
| `comparability_assessment` | Field-level comparison-readiness result | `canonical_field_id`, `source_product_id`, `target_product_id`, `status`, `reason_code`, `overall_score` |

Week 6 enum additions:

| Enum | Values |
| --- | --- |
| `CanonicalDomain` | `compute`, `object_storage`, `region`, `sla`, `product_metadata` |
| `ValueQualifier` | `exact`, `baseline`, `maximum`, `minimum`, `designed`, `supported`, `official_name`, `description`, `unknown` |
| `SpecificationScopeType` | `product`, `sku`, `product_family`, `service_tier`, `region`, `zone`, `sla`, `unknown` |
| `NormalizationRuleType` | `field_mapping`, `unit_conversion`, `qualifier_inference`, `scope_inference`, `quality_scoring` |
| `NormalizationRunStatus` | `succeeded`, `partial`, `failed` |
| `ComparabilityStatus` | `comparable`, `partial`, `not_comparable`, `needs_review` |

## Week 10 Decision Engine Tables

Week 10 adds internal-only scenario decision tables. They do not overwrite
mapping, evidence, price, or TCO records.

| Table | Purpose | Key fields |
| --- | --- | --- |
| `decision_scenario` | Versioned business scenario | `scenario_code`, `scenario_version`, `scenario_type`, `market_mode`, `workload_profile`, `scoring_policy_id` |
| `scenario_requirement` | Typed scenario requirement | `scenario_id`, `requirement_code`, `requirement_type`, `operator`, `priority`, `missing_data_policy` |
| `scoring_policy` | Versioned scenario scoring policy | `policy_code`, `policy_version`, `scenario_type`, `dimension_weights`, `thresholds` |
| `scoring_rule` | Versioned dimension rule | `policy_id`, `rule_code`, `dimension`, `operator`, `score_function`, `missing_data_policy` |
| `decision_run` | One reproducible decision run | `run_code`, `scenario_id`, `policy_id`, `mapping_cutoff`, `evidence_cutoff`, `price_cutoff`, `content_hash` |
| `candidate_decision_result` | Machine-generated internal candidate result | `decision_run_id`, `mapping_candidate_id`, `decision_status`, `business_fit_score`, `confidence_score`, `completeness_score`, `review_status`, `output_level` |
| `dimension_score` | Per-dimension fit result | `candidate_result_id`, `dimension`, `normalized_score`, `weight`, `status`, `evidence_package_id` |
| `rule_evaluation` | Hard block or rule evaluation record | `candidate_result_id`, `scoring_rule_id`, `requirement_id`, `result_status`, `hard_block`, `blocking_reason` |
| `decision_review` | Human review history | `candidate_result_id`, `reviewer`, `reviewed_at`, `decision`, `notes`, `approved_scope` |
| `decision_sensitivity_result` | Run-level sensitivity summary | `decision_run_id`, `analysis_code`, `ranking_stability`, `sensitivity_status` |

Week 10 enum additions include scenario type/status, requirement type/priority,
missing-data policy, scoring dimension, decision status, confidence level,
review status, output level, and sensitivity status.

## Week 14 Model Review Overlay

Alembic 0014 adds these tables without changing legacy human review rows:

| Table | Purpose | Key fields |
| --- | --- | --- |
| `model_review_assignment` | One review-state overlay per deterministic finding | `precheck_run_id`, `precheck_finding_id`, `target_type`, `target_id`, `input_hash`, `prior_review_status`, `review_state`, `evidence_ids` |
| `model_review_audit_event` | Append-only status-transition audit | `assignment_id`, `event_code`, `previous_status`, `new_status`, `source`, `model_id`, `reason`, `affected_records`, `downstream_rebuild_required` |

`review_state` may be `pending_model_review`, `blocked_by_deterministic_check`,
`model_review_in_progress`, `model_approved`,
`model_approved_with_conditions`, `model_rejected_reparse`,
`model_inconclusive`, `model_blocked`, `superseded`, or `expired`. The two JSON
columns use JSONB on PostgreSQL. Merely creating an assignment never changes a
business fact or grants customer eligibility.
