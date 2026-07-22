# Architecture

## Scope

`cloud-competitive-expert` is an evidence-first data foundation for a Huawei
Cloud competitive sales expert. Week 1 implements the database foundation:
structured product data, source evidence, pricing snapshots, product mappings,
reviewable competitive claims, schemas, repositories, migrations, fixtures, and
tests. Week 2 adds the source registry, raw snapshot store, ingestion audit
records, and change detection. Week 3 adds curated Huawei Cloud China-site ECS
and OBS source records, offline snapshot-backed parsers, parsed field
candidates, human review queues, quality reports, and product extension tables
for product families, storage tiers, and SLA facts. Week 4 adds AWS commercial
global EC2/S3 parsing and cloud partitions. Week 5 adds Aliyun domestic China
public cloud ECS/OSS parsing plus product-level Region and Zone availability.

Still out of scope:

- Unreviewed broad web scraping or crawler jobs.
- Provider pricing API integration.
- Embeddings, vector databases, RAG, or LLM calls.
- Streamlit or any frontend UI.
- Sales script generation.
- Competitive scoring algorithms.
- Automatic product mapping.
- Real customer data, internal quotes, secrets, or credentials.
- Unscoped provider pages, private cloud/account data, and any source outside
  the reviewed provider/partition records.

## Layers

1. Source registry layer: YAML records declare approved source identity, domain,
   terms, fetch, and storage policy before any network access.
2. Raw snapshot layer: immutable files and manifests preserve fetched bytes,
   hashes, metadata, and change reports.
3. Raw source database layer: `SourceDocument`, `SnapshotRecord`, and
   `IngestionRun` store immutable source metadata and collection audit history.
4. Parsing layer: product-specific parsers read latest raw snapshots only and
   produce `ParsedFieldCandidate` rows tied to a `ParsingRun`.
5. Evidence layer: `Evidence` stores short, locatable excerpts from a source.
6. Normalized product layer: `Provider`, `ProductCategory`, `Product`, `SKU`,
   `Region`, `AvailabilityZone`, `Availability`, `ZoneAvailability`,
   `SpecificationDefinition`, and `ProductSpecification`.
7. Product extension layer: `ProductFamily`, `ServiceTier`, and `ProductSLA`
   preserve families, object-storage classes, and SLA records without forcing
   every fact into SKU rows.
8. Review and quality layer: `ReviewItem`, `DataQualityIssue`, coverage checks,
   evidence-link validation, and JSON reports make machine extraction auditable.
9. Canonical normalization layer: `CanonicalFieldDefinition`,
   `NormalizationRule`, `NormalizationRun`, `NormalizedSpecification`, and
   `ComparabilityAssessment` provide cross-provider field standards, unit
   normalization, qualifier/scope preparation, and field-level readiness checks
   without overwriting source facts.
10. Pricing layer: `PriceSKU` describes catalog price items and
   `PriceSnapshot` stores immutable time-series prices.
11. Mapping layer: `ProductMapping` records directional Huawei-to-competitor
   mappings with scenario, status, rationale, evidence, and review status.
12. Claim layer: `CompetitiveClaim` stores evidence-backed conclusions that can
   expire and require review.
13. Evaluation layer: `SalesScenario` and `EvaluationCase` provide future test
   scaffolding without generating real sales advice.

## Provider and Market Mode

Domestic Huawei Cloud and Huawei Cloud International are modeled as separate
providers when their public sites, region catalogs, commercial rules, or source
documents differ. `MarketMode` remains a first-class field on `Product`,
`Region`, `CompetitiveClaim`, and `SalesScenario` so domestic and international
modes are preserved in the data layer rather than being a UI-only switch.

This design avoids mixing domestic and international availability or pricing
facts while still allowing future provider-level consolidation if source policy
requires it.

Provider cloud partitions keep similarly named providers from being mixed. AWS
commercial global uses `cloud_partition=aws`; Aliyun domestic public cloud uses
`cloud_partition=aliyun_public_cn`. Region and Zone parsers must filter rows
that belong to China Hong Kong, overseas, government, finance, special, or
other deferred partitions before normalized availability records are created.

## Database Strategy

- SQLAlchemy 2.x declarative models live under `src/cloud_expert/database/models`.
- Stable string enums live in `src/cloud_expert/database/enums.py`.
- Alembic migration `0001_initial_product_data_model` creates the initial
  schema with explicit constraints and downgrade support.
- Alembic migration `0002_ingestion_snapshots` adds raw snapshot and
  ingestion audit tables.
- Alembic migration `0003_week03_parsing_models` adds parsing runs, parsed
  field candidates, review items, data quality issues, product families,
  service tiers, product SLA records, and evidence provenance columns.
- Alembic migration `0004_week04_aws_partition_availability` adds cloud
  partitions and product-level availability target scope.
- Alembic migration `0005_week05_aliyun_zone_availability` adds
  `availability_zone`, `zone_availability`, and Aliyun product-family enum
  values.
- Alembic migration `0006_week06_canonical_normalization` adds canonical field,
  normalization rule, normalization run, normalized specification, and
  comparability-readiness tables.
- PostgreSQL is the target database. SQLite is used only for fast unit and
  migration tests, with documented differences.

## Week 6 Canonical Boundary

Canonical normalization is a derived layer. It maps parser field codes into
stable canonical fields, standardizes units where rules are explicit, records
value qualifiers and actual scope, and produces field-level readiness
assessments. It does not create product equivalence, competitive scoring,
pricing/TCO, customer-facing claims, or sales scripts.

## Week 3 Parsing Boundary

Week 3 parsers do not fetch the network. They load the current
`SnapshotRecord`, parse immutable raw bytes from `data/raw`, emit candidates,
create evidence excerpts, and then persist normalized product records. Each
extracted fact keeps raw value, normalized value, canonical unit when available,
parser rule, source locator, confidence, and the source snapshot hash.

Low-confidence candidates are kept, but they open `ReviewItem` rows and must not
be used as customer-facing conclusions until reviewed. Pricing text is ignored,
and SLA commitments are stored in `ProductSLA` separately from design
durability, design availability, or marketing feature text.

## Week 5 Parsing Boundary

Aliyun parsers follow the same snapshot-only rule. They parse registered Aliyun
domestic ECS/OSS raw snapshots and persist evidence-backed product facts. API
reference pages are parsed as documentation snapshots only; no AccessKey,
signed API calls, console sessions, cookies, or account data are used.

Aliyun ECS Region/Zone pages create product-level `Availability` and
`ZoneAvailability` rows. These rows do not prove that a specific ECS SKU,
instance family, OSS storage class, or feature is available in that Region or
Zone.

## Deletion Strategy

Historical evidence, source documents, price snapshots, specifications, mappings,
and claims are not cascade-deleted. Foreign keys use `RESTRICT` for historical
records and `SET NULL` only where a reviewed conclusion can survive after a
supporting optional pointer is retired.
