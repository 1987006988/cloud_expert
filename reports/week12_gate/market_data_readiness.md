# Market Data Readiness

## Current Inventory

| Metric | Count |
| --- | ---: |
| Providers | 3 |
| Provider partitions in database | 2 |
| Market mode values currently used | 3 |
| Countries in Region rows | 27 |
| Regions | 53 |
| Regions with null country | 0 |
| Regions using unresolved `ZZ` country | 2 |
| Domestic registry entries | 55 |
| International registry entries | 25 |
| Registry entries without `market_mode` | 0 |
| Registry entries without partition | 24 |
| Registry entries without `country_scope` | 80 |
| Registry entries without `region_scope` | 80 |
| Registry entries without `effective_scope` | 80 |
| SourceDocuments | 79 |
| SourceDocuments without partition | 21 |

The three currently used market-mode values are `domestic`, `international`, and
`cross_market`. The required Week 12 values `cross_market_analysis` and `unknown` are not modeled
as complete business states.

## Coverage By Layer

| Layer | Current coverage |
| --- | --- |
| Product | 4 domestic, 2 international |
| Mapping | 414 cross-market candidates; 0 human reviewed |
| EvidencePackage | 414 cross-market, internal-only packages |
| Pricing | 1 AWS S3 `us-east-1` USD snapshot, international |
| TCO | 1 complete and 5 missing-price results, all under one international scenario |
| Decision | 2,460 international-scenario results; all internal-only |
| SalesArtifact | Table absent; customer-eligible outputs 0 |

## Detected Or Contained Cross-Market Risks

- All 414 mapping candidates and all 414 evidence packages are explicitly `cross_market`.
- International decision runs contain 20 market-mode mismatch hard blocks.
- International decision runs contain 1,002 `invalid_mapping` results.
- No cross-market result is customer eligible, so the current risk is contained rather than
  customer exposed.
- TCO and Decision rows do not carry a complete provider-partition/country/region scope chain.
- 21 historical SourceDocuments have unknown partition scope.
- Registry path and language provide hints, but cannot establish missing country or effective scope.

No new market facts were inferred from URL, language, currency, or directory location.
