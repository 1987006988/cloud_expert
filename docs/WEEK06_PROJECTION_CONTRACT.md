# Week 6 Projection Contract

The Week 6 combined projection is a reproducible acceptance database built from
the Week 3 Huawei Cloud, Week 4 AWS, and Week 5 Aliyun acceptance databases.
It is not a new data ingestion task and must not introduce new providers,
products, pricing, mappings, scoring, sales scripts, frontend code, RAG, or LLM
logic.

## Required Entities

The projection must include non-zero counts for:

- `provider`
- `product`
- `product_family`
- `sku`
- `service_tier`
- `region`
- `availability`
- `product_sla`
- `source_document`
- `snapshot_record`
- `evidence`
- `product_specification`
- `parsing_run`
- `parsed_field_candidate`
- `ingestion_run`
- `review_item`
- `normalized_specification`

Aliyun data must also preserve `availability_zone` and `zone_availability`.

## Required Chain

Every sampled normalized row must resolve:

```text
NormalizedSpecification.product_specification_id
  -> ProductSpecification.id
  -> ProductSpecification.evidence_id
  -> Evidence.id
  -> Evidence.source_document_id
  -> SourceDocument.id
  -> Evidence.snapshot_record_id
  -> SnapshotRecord.id
  -> SnapshotRecord.storage_path / manifest_path
```

The raw file hash must match both `SnapshotRecord.content_hash` and the
manifest `content_sha256`.

## Stage 1 Counts

The rebuilt projection at `test_outputs/week6_combined_projection.sqlite`
validated with:

| Entity | Count |
| --- | ---: |
| provider | 3 |
| product | 6 |
| product_family | 299 |
| sku | 1709 |
| service_tier | 17 |
| region | 53 |
| availability_zone | 62 |
| availability | 102 |
| zone_availability | 62 |
| product_sla | 13 |
| source_document | 67 |
| snapshot_record | 67 |
| evidence | 14113 |
| product_specification | 10412 |
| parsed_field_candidate | 14184 |
| parsing_run | 67 |
| ingestion_run | 89 |
| cloud_partition | 2 |
| review_item | 1441 |
| normalized_specification | 10172 |

Sample chain checks passed for:

- `huawei_cloud/ecs`: 10 of 10
- `aws/ec2`: 10 of 10
- `aliyun/ecs`: 10 of 10
- `huawei_cloud/obs`: 5 of 5
- `aws/s3`: 5 of 5
- `aliyun/oss`: 5 of 5
