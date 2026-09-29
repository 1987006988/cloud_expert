# Market Scope Policy

`MarketContext` records the requested mode, country, geography, preferred
regions, provider partitions, optional currency, and tax context. Missing
currency or tax information remains unknown; it is not treated as equality.

`assess_compatibility` is purpose-specific. Mapping can compare same-market
products with partial country scope as conditional research. Pricing, TCO,
decision, and sales require progressively narrower region, currency, and tax
agreement. Domestic/international comparisons are internal research and do not
become customer-ready through a review label alone.

All customer-facing paths must use a single joined mapping, evidence package,
fresh price/TCO, and decision chain for the same scenario. Independent counts
of ready records are insufficient. Run `scripts/validate_market_scopes.py` and
the formal Week11/Week12 Gates after each upstream change.
