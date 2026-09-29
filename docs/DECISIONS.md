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

## 33. Audit Baseline Is Forward-Only Provenance

Stage 1 records the post-audit repository state as the first durable Git
baseline. The project does not reconstruct synthetic Week 1-6 commit history
after the fact. Future remediation and feature work must be committed forward
from the baseline.

## 34. Default SQLite Must Be Rebuildable

The default `cloud_expert_dev.sqlite` is a local development database, not a
source of truth. Relative SQLite URLs resolve to the project root so Alembic
commands are reproducible from different working directories. A stale default
database should be backed up, inspected, and rebuilt through Alembic rather than
patched by editing `alembic_version`.

## 35. Week 6 Projection Must Preserve Raw Provenance

The combined Week 6 projection is acceptable only when normalized rows can be
traced through product specification, evidence, source document, snapshot
record, raw bytes, and manifest hash. A projection that carries normalized rows
without snapshot-backed evidence is incomplete even if row counts look correct.

## 36. Week 9 Pricing Sources Are Reviewed By Collection Mode

Pricing sources may be approved as automated HTTP snapshots or as
manual/browser-only snapshots. Dynamic pricing pages that require client-side
rendering remain registered and reviewed, but they must not be fetched by the
HTTP fetcher unless a separate approved capture mechanism stores immutable
snapshot bytes.

## 37. Browser-Compatible HTTP Is An Explicit Fetch Policy

Some public official pricing pages reject the default project user agent while
serving the same public content to ordinary browsers. Week 9 adds a
`browser_compatible` user-agent profile so this collection method is visible in
source registry YAML and can be audited instead of hidden in ad hoc commands.

## 38. PriceSnapshot Requires Concrete Price Scope

A `PriceSnapshot` may be created only when the immutable official snapshot
contains enough scope to identify provider, product, region, unit, currency, and
numeric price. Official examples without region or list-price scope are kept as
pricing evidence but are not promoted to structured price rows.

## 39. Missing Prices Are Not Zero In TCO

Week 9 TCO line items with no official `PriceSnapshot` keep `amount=NULL` and a
`missing_reason`. They are excluded from totals and must remain visible in
reports until an approved official price snapshot is added.

## 40. Hard Rules Precede Scoring

Hard blockers are evaluated before Business Fit because scoring must not hide
market, region, data residency, architecture, SLA, evidence, review, or cost
conflicts.

## 41. Match Score Is Not Business Fit

Week 7 Match Score remains a technical similarity input. It does not represent
scenario suitability, cost position, compliance readiness, or recommendation
quality.

## 42. Business Fit Is Not Confidence

Business Fit measures scenario fit. Confidence measures trust in that judgment.
They are stored separately so high fit with weak evidence cannot look more
reliable than it is.

## 43. Missing Values Are Not Zero

Missing data is not treated as zero and not treated as full score. Mandatory
missing inputs require review or block; optional missing inputs can be excluded
from reference scoring while reducing completeness or confidence.

## 44. Blocked Candidates Are Not Ranked

Blocked candidates never receive formal rank. Reference dimension scores may be
stored for diagnosis, but rank is reserved for eligible or conditionally
eligible candidates without hard blockers.

## 45. Weights Are Scenario-Specific

Weights are scenario-specific, versioned, and validated to sum to 1.0000. This
prevents a generic score from being reused across incompatible workloads.

## 46. Provider Default Bias Is Prohibited

Scoring policy rejects provider default bonus or penalty keys. Provider
preference can only appear as explicit scenario input and must be tracked as an
assumption.

## 47. Lower TCO Is Not Overall Best

Lower TCO is not a complete recommendation. Cost Fit is one dimension and must
not override hard blockers, evidence gaps, compliance issues, or operational
constraints.

## 48. Sensitivity Is Required

Sensitivity status is stored with decision runs so unstable or indeterminate
results cannot be presented as deterministic recommendations.

## 49. Automatic Output Is A Candidate

Automatic scoring creates decision candidates only. It must not create sales
scripts, customer commitments, approved recommendations, or customer-approved
decisions.

## 50. Week 10 Defaults To Internal Only

Decision results default to `internal_only` because current evidence packages
and mapping candidates remain pending review. Customer eligibility is a
separate gate.

## 51. Review History Is Separate

Human review records are stored separately from machine-generated results. New
rules or reruns must preserve historical results and review history.

## 52. Model Review Replaces New Manual Queue Work, Not History

The owner removed the requirement for new row-by-row human review. Existing
human records remain immutable history; Week14 adds a separate model-review
assignment and audit overlay. A model decision must never be labeled
`human_reviewed`, `human_approved`, or `customer_approved`.

## 53. Highest Verified Reasoning Model, No Silent Fallback

The capability registry selects the highest approved and runtime-verified
model. A weaker model cannot be substituted without an explicit policy change.
The model alias, CLI version, prompt version, input hash, and unresolved
snapshot-version limitation are recorded.

## 54. Generation, Primary Review, Challenge, and Arbitration Are Isolated

The generating pipeline does not approve its own output. Review stages use
independent contexts and structured inputs only; adversarial review searches
for semantic, scope, market, price, and evidence faults. A disagreement needs
independent adjudication; unresolved or invalid output remains inconclusive.

## 55. Deterministic Checks Precede Model Judgment

Hash, link, schema, market, arithmetic, and status-transition checks are
repeatable and cheaper than model judgment. Failing such a check blocks model
approval, including when a model's language sounds confident.

## 56. Root Cause Repairs Precede Re-review

Repeated extraction errors must be clustered by parser root cause. Repairs
change parser/normalizer code and rebuild derived records from immutable raw
snapshots; direct database fact edits would break provenance. Every repair
requires tests, impact counts, and preserved historical outputs.

## 57. Model Availability Is Not Data-Transfer Authorization

A read-only model probe established availability without sending business
data. The environment safety reviewer rejected transfer of local review
subjects and Evidence excerpts. Live review remains disabled until that
specific transfer is authorized; an available model is not an approved run.

## 58. Evals Must Block Release When Critical Coverage Is Missing

Synthetic deterministic cases establish a reproducible baseline, not a full
system score. Missing categories, unmeasured metrics, sub-85% code coverage,
unsupported customer claims, or failed critical invariants keep Week14 and
customer output NO-GO. Customer commitments cannot be inferred from a model
verdict or a passing subset of tests.

## 59. Dataset Authorization Is Narrow

The owner authorized only official-source excerpts, mapping candidates, and
necessary IDs for `gpt-6-astra` review. This does not include customer data,
secrets, customer-output approval, or permission to transmit other review
object classes without their own data controls.

## 60. Model Input Uses Stdin and Technical Attempts Stay Auditable

On Windows, passing JSON as a `.CMD` argument produced unreliable model input
and copied it into a timeout error. The pilot now uses UTF-8 stdin and redacted
technical errors. Failed attempts remain separate from successful runs.

## 61. Adjudication Precedes Disposition, But Cannot Force Approval

An adversarial reparse suggestion is not proof of a parser defect. The final
decision considers independent adjudication before assigning reparse; any
unresolved disagreement or attempted approval over an adverse opinion stays
inconclusive. Inconclusive, blocked, reparse, and conditional states remain
Gate blockers.

## 62. Migration Tests Must Never Inherit an Acceptance Database URL

Alembic's environment variable takes priority over a test Config URL. Tests
now clear `DATABASE_URL` and use unique temporary SQLite files, so an
acceptance or production-like database cannot be targeted accidentally.
