# Evidence Policy

## Rule

No real product fact may be promoted unless it can be traced through:

1. A reviewed registry YAML source.
2. An immutable raw snapshot and manifest.
3. A `SourceDocument` and `SnapshotRecord`.
4. A short `Evidence` excerpt.
5. A parser rule or manual review decision.

This policy applies to product names, descriptions, SKU parameters, storage
tiers, SLA percentages, Region statements, Zone statements, capability fields,
mappings, and future sales claims.

## Week 3 Evidence Metadata

`Evidence` now records:

- `source_document_id`.
- `section_title`.
- `locator`.
- `excerpt`.
- `evidence_type`.
- `confidence`.
- `review_status`.
- `page_title`.
- `snapshot_record_id`.
- `content_hash`.
- `parser_rule`.

The excerpt should be the smallest useful passage needed to support the field.
Long source passages, copied documentation pages, and broad page summaries are
not acceptable evidence records.

## Review Triggers

A `ReviewItem` is required when:

- Parser confidence is below the configured threshold.
- A value is inferred from a heading, SKU code pattern, or adjacent table
  context.
- Sources disagree or a newer snapshot changes a previously parsed value.
- The value would be used in a customer-facing comparison, recommendation, or
  sales narrative.

## SLA Handling

SLA percentages and compensation scope are stored in `ProductSLA`. They must not
be merged with object-storage design durability, design availability, product
marketing wording, or generic availability claims.

## Availability Handling

Positive `Availability` and `ZoneAvailability` statuses require evidence.
Product-level Region or Zone evidence must not be promoted into SKU-, family-,
storage-class-, feature-, or customer-facing availability claims without a more
specific source and review decision.

## Current Review State

The Week 5 Aliyun acceptance run has 8039 Aliyun evidence records and 0 missing
evidence links. Eighty-two Aliyun review items remain open: 70 ECS items and 12
OSS items. Human review is not complete.
