# Mapping Review Guide

Mapping review is a controlled human step. A mapping candidate is not customer
usable until a named reviewer records a decision, time, and notes.

## Decision Rules

- `human_reviewed`: evidence supports the source and target entities, mapping
  level, relationship type, field comparisons, and stated conditions.
- `rejected`: evidence does not support the mapping or the candidate mixes
  incompatible products, regions, scopes, or units.
- `pending_review`: the candidate is machine generated or lacks enough reviewed
  evidence for customer use.

## Required Checks

Reviewers must verify:

- source and target provider, product, SKU, family, or service-tier identity;
- official evidence references and source freshness;
- unit, qualifier, scope, and market-mode compatibility;
- all blocking reasons and conditions;
- no rejected normalized value or rejected SLA evidence is used;
- pricing and TCO dependencies are complete when the mapping feeds a decision.

## Audit Requirements

Review decisions must be written through repository scripts or database-backed
review tables. CSV notes alone are not sufficient. Historical machine-generated
results must remain traceable through review import audit rows.
