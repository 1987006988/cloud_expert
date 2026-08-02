# Compute Mapping Policy

Compute candidates are evaluated at product, family, SKU, and service-tier
levels when evidence exists.

Mandatory safeguards:

- CPU architecture conflicts are hard blockers when the scenario declares a
  required architecture.
- Product-level facts do not replace SKU-level facts.
- Region and market-mode scope must match the scenario before customer use.
- Match Score is only a technical similarity input. It is not Business Fit,
  Confidence, or a recommendation.
- Pending-review mappings remain internal-only.
