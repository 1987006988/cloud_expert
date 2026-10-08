# Oct9 Read-Only Freshness Audit

Checked at 2026-10-09 00:52-00:57 Asia/Shanghai (2026-10-08 16:52-16:57 UTC).
Business database: `test_outputs/week6_combined_projection.sqlite`, NOT the tiny root default database.
Before/after database SHA256: `a2f46d6e5e3afee2c114d6dd07ffa57af5780dfd93a9955ebac04377729dd6f2`.
SQLite URI mode=ro, query_only=ON, autoflush=False, clean session; no network/model calls, business writes, or Gate changes. No FK violations.

## AWS: Exact Current Blocker

Small reproducible diagnostic: `aws_failure.json` (not the large overall audit).

| Price pair | Catalog snapshot | Policy Evidence / snapshot | Live result |
| --- | --- | --- | --- |
| 13 -> 19 | 95 | 29338 / 105; 29342 / 107 | blocked |
| 17 -> 20 | 95 | 29338 / 105; 29343 / 107 | blocked |
| 18 -> 21 | 96 | 29344 / 108; 29339 / 105; 29338 / 105 | blocked |

All three persisted successor derivation configs specify `max_age_days=7`.
The immediate real-time exception is `official snapshot provenance, authorization or freshness invalid` at `src/cloud_expert/pricing/aws_billing_policy.py:92`; the expired-window predicate is line 90. It is called by `aws_document_catalog.py:379`, from `aws_price_replacement.py:411`. The public resolver deliberately condenses this into `aws_replacement_proof_failed` at lines 429-436.

- Catalog 95 expired after 2026-10-06 17:34:39.739470 UTC; catalog 96 after 17:48:05.637523 UTC.
- Policies 105/107/108 expired after 18:55:16.179015 / 18:55:51.093687 / 18:56:26.701129 UTC that day. Independent policy API calls at the real current time fail at `aws_document_policy.py:175` (age predicate at line 171).
- This is NOT detected code/registry drift: all 147 frozen03 pricing-code and registry files checked match their recorded hashes.
- Receipt-bound old/new price rows and policy rows remain identical. All five raw hashes still match both DB and manifests; capture times match; source admission remains enabled/approved; snapshots/documents still current. Expiry is established without changing the clock or extending the configured window.
- Generic `price_snapshot_freshness` still says fresh because its window is 14 days; that does not override this stricter 7-day proof.

## Refresh Requirements

Refresh these authorized sources into NEW immutable snapshots: `aws_s3_pricing_bulk_us_east_1`, `aws_ec2_pricing_bulk_us_east_1`, `aws_pricing_principles`, `aws_s3_billing_usage_codes`, `aws_ec2_instance_lifecycle_billing`. Exact official URLs are in the small diagnostic JSON. Do not use withdrawn website policies 98/99 or metrics-only storage evidence 106.

Re-extract policy Evidence and exact S3 PUT/GET and EC2 m6i.xlarge catalog selections; preserve rates, units, currency, region, tax uncertainty and complete tier groups. Do not change old timestamps, evidence, configs, max_age_days or vendor effective dates.

Important lifecycle prerequisite: a fresh capture alone cannot repair the old 13->19 / 17->20 / 18->21 receipts. `aws_replacement_disposition` reconstructs the successor's fixed `derivation_config` (lines 405-421), and `_catalog_facts` also applies current freshness to that catalog (lines 114-121). Capture archival changes may additionally invalidate old row fingerprints. A separately audited append-only renewal/retirement transition with explicit fresh successor bindings is needed before old expired rows can leave active errors; existing provenance checks must remain fail-closed. Do not simply replay the old replacement CLI or overwrite its old document plan.

## Separate Decision / Mapping State

- Fresh proven domestic prices: 2-12. Scoped TCO19 (Huawei, prices7/8/9, policies14195/14196) and TCO21 (Aliyun, prices10/11/12, policies14200/14211) still recompute complete and valid now. They remain separate bounded 730h/720h scenarios, not cross-vendor comparable or customer-approved.
- TCO20 is preserved old partial history (missing ip_holding); TCO21 is its complete newer scenario version. Other TCO1-18 fail current completeness.
- AWS quarantine 1/14/15/16 still has valid live rejection proof, not approval or replacement coverage.
- Mapping649 retains valid category-only approval and intact evidence, but is `due_soon`: Evidence14143/14144 bind SourceDocument/Snapshot1/52 captured July22. Current packages1068/1481 are ineligible. Refresh those documentation sources, rebuild derived evidence/mapping/packages and perform new bound review if the subject changes; do not merely relabel the old approval.
- Decision10281 (scenario7/run35/mapping649/TCO21), 9587 and 9196 all fail `decision_engine_or_dependencies_outdated`. The other viable historical IDs are 397/791/1185/1209/1233/1257/1651/1675/2069, also outdated. This is separate from AWS proof expiry: Decision fingerprints include UTC `freshness_day` (`decision/pipeline.py:733`), plus implementation/dependency state. Current condition-core edits were observed during this audit, so this is not a new frozen-code certification. After code freeze and data refresh, append a fresh engine run and rebuild/precheck its actual new ID before model review.
- Mapping freshness across 952 candidates: 912 stale, 34 due_soon, 6 unknown; only649 currently has approved candidate status. Exact IDs and evidence dependencies remain in `mappings.json`; do not use this audit to approve them.
- Docker default and desktop-linux pipes are both unavailable. CLI exists; existing container state cannot be determined. Nothing started/deleted.

## Safe Next Commands (Not Executed Here)

Read-only verification in a dedicated PowerShell session:
```powershell
$env:DATABASE_URL = 'sqlite:///file:D:/cloud_expert/test_outputs/week6_combined_projection.sqlite?mode=ro&uri=true'
.\.venv312\Scripts\python.exe -B scripts/validate_price_evidence.py
docker --context desktop-linux ps -a
```

Coordinator order: finish/freeze the condition contract; refresh admitted AWS/catalog-policy and mapping sources with preserved history; implement/test the exact append-only expiry disposition; revalidate prices/TCO/packages; generate a current Decision; run precheck; only then authorize independent primary/adversarial model review and controlled writeback. Fresh domestic price10-12 leave strict `fresh` after 2026-10-10 15:52:49.469 UTC, so recheck immediately before the run. No aggregate GO is claimed.

Audit setup notes: two initial local driver attempts failed before output generation (Windows platform warmup blocked by the process guard; then an incorrect ORM attribute name). Both were fixed only in the report-local driver. No source or business database modification occurred.
