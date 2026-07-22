# Decisions

## 1. Provider and MarketMode

Domestic Huawei Cloud and Huawei Cloud International can be represented as
separate `Provider` records because source sites, catalogs, and availability can
diverge. `MarketMode` is still stored on products, regions, scenarios, and
claims so domestic/international behavior is queryable at the data layer.

## 2. Specification Definitions and Values Are Separate

`SpecificationDefinition` defines the meaning, type, and canonical unit of a
parameter. `ProductSpecification` stores actual values, raw values, canonical
values, evidence, and validity windows. This avoids unbounded JSON blobs and
supports typed comparison.

## 3. Prices Use Snapshots

Provider prices change over time and must not overwrite history.
`PriceSnapshot` preserves point-in-time values, discount type, effective dates,
evidence, and payload path.

## 4. Evidence Is a Separate Model

Many entities need support from the same source excerpt. A standalone
`Evidence` table avoids duplicating excerpts and lets review status, confidence,
and locator metadata travel with the supporting fact.

## 5. ProductMapping Is Not a Generic Many-to-Many Table

Competitive mapping is directional, scenario-specific, reviewable, and may be
`none`, `partial`, or `pending_review`. Treating it as a simple many-to-many
relationship would imply symmetry and equivalence that may be false.

## 6. Real Competitive Claims Need Manual Review

Competitive conclusions can affect customer-facing sales work. They must record
evidence, conditions, limitations, confidence, validity windows, and review
status before use.

## 7. SQLite Is Only a Fast Test Substitute

SQLite is used for unit and migration tests because it is fast and requires no
external service. PostgreSQL remains the target database. Differences include
temporary migration bookkeeping behavior and some constraint/index enforcement
details; final migration checks must run on PostgreSQL when available.

## 8. Source Registry Precedes Extraction

Week 2 adds YAML source registry records before any product fact extraction.
Registry entries declare authority, terms status, domain policy, fetch policy,
and storage policy so official sources can be reviewed independently from later
parsers.

## 9. Raw Snapshots Are Immutable Files Plus Database Indexes

Fetched bytes are stored as files with SHA-256 hashes and manifests. The
database stores `SnapshotRecord` rows for queryability and `SourceDocument`
rows for continuity with the evidence model. Identical content is deduplicated
per source id.

## 10. Every Fetch Attempt Gets an IngestionRun

Successful, unchanged, failed, blocked, skipped, and dry-run attempts are
recorded. This keeps operational audit history separate from source evidence.

## 11. Network Safety Is Part of the Data Model Boundary

The fetch layer blocks private IP targets, metadata IPs, unsafe schemes, unsafe
ports, credentials in URLs, and redirects outside source policy. These controls
are included in Week 2 because source registration without safe collection would
create a misleading foundation.

## 12. Test Sources Must Stay Synthetic

The checked-in registry uses `.invalid` URLs and fixture response files. This
keeps tests deterministic and avoids introducing real cloud product facts before
source review and evidence extraction rules are ready.

## 13. Week 3 Uses Curated Huawei Cloud Domestic Sources Only

The first real provider scope is limited to public Huawei Cloud China-site ECS
and OBS pages. International Huawei Cloud, AWS, Aliyun, community content,
console pages, customer data, account-specific data, and pricing pages are
excluded until separate source review and task scope approve them.

## 14. Parsers Read Snapshots, Not The Network

Product parsers operate after ingestion has produced immutable raw snapshots.
They never issue HTTP requests, which keeps source access policy separate from
field extraction and makes parser tests deterministic.

## 15. ParsedFieldCandidate Is An Audit Boundary

Each extracted value is first stored as a parsed candidate with raw value,
normalized value, canonical unit, locator, excerpt, confidence, parser rule, and
target identity. Normalized product rows are derived from candidates rather than
from parser-local side effects.

## 16. Evidence Carries Snapshot Provenance

Week 3 extends `Evidence` with page title, snapshot id, content hash, and parser
rule. This lets every extracted product fact point back to the exact official
snapshot bytes and extraction rule that produced it.

## 17. SLA Records Are Separate Product Facts

SLA availability commitments are stored in `ProductSLA`. They are not merged
with OBS design durability, OBS design availability, ECS service descriptions,
or generic feature text because those values have different meaning and review
requirements.

## 18. ECS Families, ECS SKUs, And OBS Storage Classes Are Different Shapes

ECS instance families are represented as `ProductFamily` and concrete instance
types as `SKU`. OBS storage classes are represented as `ServiceTier`, not SKU,
because storage classes are service tiers rather than provider SKU codes in the
current source set.

## 19. Low-Confidence Values Stay Visible But Blocked

Low-confidence parser output is kept for audit and parser improvement, but it
opens `ReviewItem` rows and cannot be treated as reviewed product truth. The
initial open queue contains ECS instance-family and OBS retrieval-description
items.

## 20. Product-Level Region Evidence Does Not Prove SKU Availability

Region and AZ documentation can support product-level region evidence, but it
must not be used to claim every ECS SKU or every OBS storage class is available
in every region.

## 21. Reparse Must Be Idempotent For Normalized Facts

Repeated parsing of unchanged snapshots may add new `ParsingRun` and
`ParsedFieldCandidate` audit rows, but it must not duplicate products, SKUs,
families, service tiers, SLA records, evidence, or normalized specifications.

## 22. Pricing Text Is Ignored In Week 3

Any pricing references encountered on product or documentation pages are ignored
by the parsers. Real pricing ingestion remains blocked until a dedicated pricing
source policy, schema review, and acceptance task are completed.

## 23. AWS Commercial Is A Cloud Partition, Not The Whole Provider

Week 4 models AWS commercial global as `provider_code=aws` with
`cloud_partition=aws`. AWS China and AWS GovCloud are deferred partitions and
must not be mixed into the commercial Region or availability dataset.

## 24. AWS EC2 And S3 Reuse Evidence-First Product Shapes

EC2 instance types are SKUs and EC2 families are product families. S3 storage
classes are service tiers. Region endpoint pages create product-level
availability only and do not prove SKU-, family-, storage-class-, or
feature-level availability.

## 25. Pricing Pages May Be Registered Disabled

Week 4 registers EC2 and S3 pricing pages as disabled/manual-only sources so
future pricing work can see the reviewed candidate URLs. They are not fetched,
parsed, or used for product facts in the AWS baseline.

## 26. Week 5 Uses Aliyun Domestic Mode

The Week 5 user prompt supersedes the previous backlog proposal for Aliyun
overseas mode. Week 5 uses `provider_code=aliyun`, `market_mode=domestic`, and
`cloud_partition=aliyun_public_cn`. Aliyun international `alibabacloud.com`
pages, China Hong Kong, overseas, government, finance, special-cloud, console,
and account-specific sources remain out of scope.

## 27. Aliyun Zones Are First-Class Availability Evidence

Aliyun ECS official Region/Zone documentation includes Zone-level facts that
should not be collapsed into Region-only availability. Week 5 adds
`AvailabilityZone` and `ZoneAvailability` so product-level Zone availability can
be audited without implying SKU-, family-, storage-class-, or feature-level
availability.

## 28. Aliyun API Reference Pages Are Source Documents, Not API Calls

DescribeInstanceTypes, DescribeRegions, and DescribeZones pages are registered
and parsed as public official documentation snapshots. Week 5 does not call
provider APIs, use AccessKeys, sign requests, scrape console pages, or ingest
account-specific data.

## 29. Aliyun Pricing Pages Stay Disabled

Week 5 registers ECS and OSS pricing URLs as disabled/manual-only sources for
future review. They are not fetched, parsed, normalized, or used in product
facts, TCO, mapping, scoring, or sales output.

## 30. Week 6 Adds A Derived Canonical Layer

Canonical values are stored in `NormalizedSpecification` rows linked back to
`ProductSpecification` and `Evidence`. The source product facts are not
renamed, overwritten, or deleted. `NormalizationRun` provides an idempotency key
and rollback boundary for derived rows.

## 31. Comparability Is Readiness, Not A Competitive Conclusion

`ComparabilityAssessment` records whether a field has enough aligned evidence,
unit, qualifier, and scope to be considered ready for later comparison. It must
not be presented as product equivalence, superiority, TCO guidance, pricing
advice, sales copy, or an automatic product mapping.

## 32. Service-Tier Scope Gaps Stay Visible

Object storage canonical fields default to `service_tier` scope, but current
`ProductSpecification` rows do not persist a direct service-tier foreign key.
Week 6 keeps those normalized facts with product scope and flags the mismatch
instead of inventing service-tier identity.
