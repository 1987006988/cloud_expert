# Data Governance

## Source Registry Layer

Official source records must be reviewed before automated collection. The
registry stores authority level, market mode, domain policy, fetch policy,
storage policy, optional cloud partition, terms review status, and automation
flags. Synthetic fixture entries are allowed only on `.invalid` URLs.

## Raw Source Layer

`SourceDocument` records document-level source metadata: URL, content hash,
capture time, authority level, language, and storage path. `SnapshotRecord`
indexes immutable raw snapshots and `IngestionRun` audits each collection
attempt. Raw versions must not be overwritten. `is_current` marks the
recommended current version only.

## Raw File Layer

Raw snapshot files live under `data/raw` by default and are ignored by Git.
Each snapshot has a manifest, raw bytes, sanitized response headers, metadata,
and a change report. Hashes are used for integrity and duplicate detection.
Temporary writes must be atomic.

## Evidence Layer

`Evidence` stores the minimum excerpt needed to support a field or conclusion.
Each evidence row includes locator information such as section, page, HTML
selector, JSON path, or API field. Confidence is normalized to `0..1`.

## Normalized Data Layer

Structured rows such as `Product`, `Region`, `AvailabilityZone`, `SKU`, and
`ProductSpecification` store normalized facts. Product-level, region-level,
Zone-level, SKU-level, and price facts are separated so later workflows do not
compare unlike entities.

Provider partitions are explicit. AWS commercial global (`aws`) and Aliyun
domestic public cloud (`aliyun_public_cn`) facts must not be merged with China
Hong Kong, overseas, government, finance, special, or account-specific scopes.

## Pricing Snapshot Layer

`PriceSKU` defines catalog price items. `PriceSnapshot` stores point-in-time
prices. Prices are append-only and retain billing period, discount type, region,
currency, and evidence. Internal contract prices are not allowed in this phase.

## Mapping Layer

`ProductMapping` records directional mappings with level, status, scenario,
rationale, optional SKU scope, evidence, and review status. A mapping is not
assumed to be reversible.

## Competitive Claim Layer

`CompetitiveClaim` stores evidence-backed conclusions with applicable
conditions, limitations, confidence, review status, and validity windows. Week 1
implements the model only and does not generate real claims.

## Review Workflow

1. Machine extraction or manual entry creates evidence-linked records.
2. Records start as `pending_review`, `machine_extracted`, or `unknown`.
3. A reviewer sets `human_reviewed` or `rejected`.
4. Downstream competitive outputs may only rely on reviewed or explicitly
   accepted evidence according to future policy.

## Expiration Strategy

- Use `last_verified_at` for facts that need periodic revalidation.
- Use `valid_from` and `valid_to` for specifications and claims.
- Use new price snapshots instead of updating old prices.
- Keep historical source documents even when `is_current=false`.

## Sensitive Data Rules

The repository must not contain customer names, account IDs, credentials,
secrets, internal quotes, or company-sensitive commercial terms. Test data must
use `synthetic`, `fixture`, or `sample` names and `.invalid` URLs.

## Ingestion Safety Rules

- Block authentication-required, browser-required, and manual-only sources.
- Block private network targets, metadata IPs, unsafe ports, and unsafe
  redirects.
- Store sanitized response headers only.
- Keep network tests opt-in; default tests use local synthetic fixtures.
