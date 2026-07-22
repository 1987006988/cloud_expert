# Week03 Audit

## Verdict

**PASS_WITH_RISK.** Huawei Cloud ECS/OBS source ingestion and parsing are supported by database evidence, but human review is incomplete and Region/Availability remains unstructured.

## Verified Counts

- Source documents: 21.
- Snapshot records: 21.
- Ingestion runs: 21.
- Parsing runs: 21.
- Evidence records: 351.
- Product specifications: 228.
- SKUs: 37.
- Product families: 17.
- Service tiers: 4.
- Product SLA records: 7.
- Review items: 9.

## Evidence Chain

Sampled 10 product specifications across ECS/OBS. All sampled rows linked ProductSpecification -> Evidence -> SourceDocument -> SnapshotRecord.

## Risks

- 9 open low-confidence review items.
- 0 normalized Region rows and 0 Availability rows in Week3 acceptance DB; region material is product-level evidence only.
- Current `validate_evidence_links.py` fails on the unupgraded Week3 DB because it assumes Week5 tables; the upgraded audit copy validates.
