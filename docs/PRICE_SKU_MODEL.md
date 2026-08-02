# Price SKU Model

`PriceSKU` represents a provider price identity scoped to provider, product,
region, charge category, billing mode, billing unit, currency, and tax flag.

`PriceSnapshot` stores the captured unit price and evidence link for a specific
pricing observation.

The model separates SKU identity from price observations so future price changes
produce new immutable snapshots rather than overwriting historical evidence.
