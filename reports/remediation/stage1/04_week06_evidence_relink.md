# Week 6 Evidence Relink

The projection builder now copies snapshot, ingestion, parsing, review, product
shape, SLA, partition, region, and availability tables.

Rebuilt projection validation:

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
