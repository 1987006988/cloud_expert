# Week04 Audit

## Verdict

**PASS_WITH_RISK.** AWS EC2/S3 baseline is evidence-backed and partition validation passes, but human review and current-validator compatibility remain risks.

## Verified Counts

- Source documents: 22.
- Snapshot records: 22.
- Ingestion runs: 44.
- Parsing runs: 22.
- Evidence records: 5723.
- Product specifications: 3873.
- EC2 SKUs: 678.
- EC2 product families: 74.
- S3 service tiers: 8.
- Regions: 34.
- Availability rows: 68.
- Review items: 1350.

## Validation

- `validate_source_registry.py --provider aws`: 24 valid, 2 disabled, 0 errors.
- `validate_provider_partitions.py --provider aws --partition aws`: 0 violations.
- Evidence-chain sample passed on original Week4 DB.

## Risks

- 1350 open review items block customer-facing use.
- Availability rows are product-level only and cannot prove SKU/family/storage-class availability.
- Current `validate_evidence_links.py` fails on the unupgraded Week4 DB because it assumes Week5 zone tables; the upgraded audit copy validates.
