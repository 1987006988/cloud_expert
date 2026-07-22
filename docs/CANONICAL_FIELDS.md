# Canonical Fields

Canonical fields are stable comparison-preparation fields. They are deliberately
separate from parser field codes so source parsers can keep provider-specific
wording while downstream workflows use consistent names.

Generated field matrices:

- `reports/normalization/compute_field_matrix.md`
- `reports/normalization/compute_field_matrix.csv`
- `reports/normalization/object_storage_field_matrix.md`
- `reports/normalization/object_storage_field_matrix.csv`

## Naming Rules

- Use domain prefixes: `compute.*` and `object_storage.*`.
- Put physical resource concepts before metric names, for example
  `compute.memory.capacity_gib`.
- Keep value qualifiers out of the raw legacy field where possible; store them
  in `value_qualifier`.
- Use explicit unit suffixes only where they prevent ambiguity, such as `_gib`
  or `_percentage`.

## Current Domains

| Domain | Canonical fields | Legacy mappings |
| --- | ---: | ---: |
| Compute | 19 | 21 |
| Object storage | 19 | 19 |
| Total | 38 | 40 |

## Non-Goals

Canonical fields do not assert that two providers have equivalent products.
They only define a field vocabulary and normalization target for future
evidence-backed analysis.

