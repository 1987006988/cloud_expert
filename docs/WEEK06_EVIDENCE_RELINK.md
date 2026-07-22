# Week 6 Evidence Relink

Stage 1 restored the Week 6 provenance chain:

`NormalizedSpecification -> ProductSpecification -> Evidence -> SourceDocument -> SnapshotRecord -> raw file + manifest`

## Audit Failure

The original Week 6 combined projection copied product specifications and
evidence rows but did not preserve the full snapshot and parsing context. In
the audited projection, `snapshot_record`, `ingestion_run`, `parsing_run`,
`parsed_field_candidate`, and review/product-shape tables were missing from the
combined dataset.

## Fix

`scripts/build_week6_combined_acceptance.py` now copies or remaps:

- `SnapshotRecord`
- `IngestionRun`
- `Evidence.snapshot_record_id`
- `CloudPartition`
- `Region`
- `ProductFamily`
- `ServiceTier`
- `ProductSLA`
- `Availability`
- `AvailabilityZone`
- `ZoneAvailability`
- `ParsingRun`
- `ParsedFieldCandidate`
- `ReviewItem`
- `DataQualityIssue`

It also converts raw SQLite datetime strings when copying availability rows.

## Relink Tool

`scripts/relink_normalized_evidence.py` can conservatively repair existing
databases:

- relink `Evidence.snapshot_record_id` when exactly one matching snapshot can
  be found
- relink `NormalizedSpecification.evidence_id` to its source
  `ProductSpecification.evidence_id`
- refuse ambiguous snapshot candidates
- support `--dry-run`

## Stage 1 Result

The rebuilt Week 6 projection passed:

```text
scripts/relink_normalized_evidence.py --dry-run
unresolved_total: 0

scripts/validate_normalized_evidence.py
normalized_specifications: 10172
missing_product_specification: 0
missing_evidence_links: 0
evidence_mismatch: 0
missing_source_document: 0
missing_snapshot_record: 0
missing_manifest: 0
missing_raw_file: 0
hash_mismatch: 0
checked_raw_files: 35
```
