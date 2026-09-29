# Market Mode Architecture

Market mode is an explicit property of products, partitions, regions, scenarios,
and derived results. `domestic`, `international`, and `cross_market_analysis`
are distinct; an unknown scope is never silently inferred to be compatible.

`cloud_expert.market.scopes` resolves an entity to a `MarketScope` and applies
versioned compatibility rules. Domestic/international differences return
`cross_market`. Country, region, partition, currency, and tax mismatches are
checked according to the operation. Cross-market analysis is internal-only.

Reference `MarketContext` rows are generated from evidence-backed region
availability and explicit provider partitions. They omit currency and use
unknown tax context rather than inventing commercial terms. A compatibility
assessment is a routing aid, not approval of a product, price, or sales claim.

The active integrity scan must report zero missing source partitions, unknown
region countries, active TCO market mismatches, and customer-exposed cross-market
results. Historical mismatches remain visible for remediation, not deleted.
