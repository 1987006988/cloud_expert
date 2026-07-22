# Product Scope

## MVP Market Scope

Domestic mode:

- Huawei Cloud
- Aliyun / Alibaba Cloud China public cloud

International mode:

- Huawei Cloud International
- AWS

## First Product Categories

- Compute
- Object storage
- MySQL-compatible relational database
- Redis-compatible in-memory database

The data model reserves codes for future categories such as network, container,
security, AI, analytics, migration, and hybrid cloud.

## Week 1 Boundaries

Week 1 provides model capacity only. It does not assert real provider product
facts. Synthetic test data uses `synthetic` names and `example.invalid` URLs.

Week 5 domestic Aliyun facts are limited to `cloud_partition=aliyun_public_cn`.
Aliyun international, China Hong Kong, government, finance, special cloud,
console, and account-specific facts remain out of this completed slice.

Future real facts must be represented as:

1. `SourceDocument`
2. `Evidence`
3. Normalized entity rows linked to evidence
4. Review status and confidence
