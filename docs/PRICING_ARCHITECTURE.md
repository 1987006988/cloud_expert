# Pricing Architecture

Week 9 pricing uses official source registration, immutable raw snapshots,
`SourceDocument`, `Evidence`, `PriceSKU`, `PriceSnapshot`, and TCO calculation
records.

Pricing safeguards:

- source terms and collection mode are reviewed before ingestion;
- raw snapshots are immutable evidence inputs;
- missing price dimensions stay missing;
- missing prices are not converted to zero;
- directory price is not customer transaction price;
- discounts, private offers, tax treatment, and exchange rates require explicit
  policy and evidence before use.
