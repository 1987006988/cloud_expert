# Provider Partition Policy

A cloud partition is a source and availability boundary. Registry entries state
their provider, market mode, and partition. Source documents preserve the
matched partition without changing raw bytes or evidence hashes.

Region records must point to a compatible partition and have an explicit
country code supported by availability evidence. Unknown country (`ZZ`) is a
blocker, not a default. Pricing evidence must match the price SKU's region and
partition; conflicting source scopes cannot be combined into a customer quote.

Backfills use exact provider/URL/registry matching and emit a separate audit
manifest. They do not rewrite a historical source snapshot. Validate with
`scripts/validate_market_partitions.py` and `scripts/validate_regions.py`.
