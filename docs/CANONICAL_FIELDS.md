# Canonical Fields

Canonical fields are stable comparison-preparation fields. They are deliberately
separate from parser field codes so source parsers can keep provider-specific
wording while downstream workflows use consistent names.

Generated field matrices:

- `reports/normalization/compute_field_matrix.md`
- `reports/normalization/compute_field_matrix.csv`
- `reports/normalization/object_storage_field_matrix.md`
- `reports/normalization/object_storage_field_matrix.csv`

Stage 2 field matrices include semantic, unit, qualifier, scope, evidence,
comparability, lifecycle, replacement, and review-policy status columns.

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

## Governance Metadata

Canonical field seeds publish the following metadata into
`canonical_field_definition.metadata_json`:

- `semantic_group`
- `semantic_status`
- `unit_status`
- `scope_status`
- `qualifier_status`
- `evidence_requirement`
- `evidence_status`
- `comparability_tier`
- `comparability_status`
- `review_policy`
- `lifecycle_status`
- `deprecated`
- `replacement_field_code`

## Non-Goals

Canonical fields do not assert that two providers have equivalent products.
They only define a field vocabulary and normalization target for future
evidence-backed analysis.
