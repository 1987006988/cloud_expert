# October 9 Prerequisite Recovery

This is an in-progress checkpoint, not a Gate approval or release receipt.

## Verified Work

- Implemented `decision_conditions.v1`: canonical executable condition text,
  strict registry/proof binding, mandatory scope checks and unknown-condition
  preservation for negative reviews. Unknown conditions cannot authorize approval.
- Decision prompt v5 and writeback v3 bind the registry and recheck it on use.
  Focused synthetic verification: 363 condition/panel/scenario-binding tests and
  89 controlled-writeback tests passed. Earlier failing attempts remain historical.
- Added approved-mapping refresh preparation with subject CAS, append-only new
  candidate/precheck records, strict replay checks and no alteration of the old
  approved candidate or its review history. Mapping refresh/revision: 38 tests passed.
- Docker startup failed on an inaccessible stale runtime socket. With Docker
  stopped, its runtime directory was preserved as `run.blocked-20261009`; no
  container, volume or configuration was deleted. The existing isolated R011
  container now responds to `pg_isready`; reserved database `_04` has zero public
  tables. New frozen PostgreSQL verification has not yet run.
- Codex CLI reported 0.158.0. An isolated, data-free gpt-6-astra connectivity probe
  returned the expected marker. This is not a business review or model identity
  attestation. Probe stdout SHA256:
  `0d986fc55853b11d43aa0443a01a52c99467db7e8be4a21fd51ea332ac72a285`.

## Controlled Data Changes

Before writes, SQLite backup `test_outputs/gate_recovery_before_refresh_20261009_01.sqlite`
passed `integrity_check=ok`; SHA256:
`9e7f6a282bb9f2d7b83d05b8533c33b245130ea5a149eb997aeb86ac48cb72d9`.

| Source | New Snapshot | Capture UTC | Raw SHA256 |
| --- | --- | --- | --- |
| huawei_cloud_ecs_documentation_intro | 119 | 2026-10-08 16:59:48 | beb0b762aaecd068a50ab1b98221c57b72af562b6740b408d3e4e38d18723296 |
| aliyun_ecs_what_is_ecs | 120 | 2026-10-08 17:00:10 | c1fe42ff43e31fcc5e1b1ffd03d3987b4d328d5493d7ac9481bd093cc1a41150 |

Both registered public sources returned HTTP 200 and content changes. Parsing runs
135/136 created Evidence 34142-34146. Product-definition Evidence is 34143/34146.
Old immutable bytes, capture timestamps and evidence rows were retained; current
snapshot flags follow normal source-version archival.

Mapping649's expected subject SHA256 was
`62705deaf1f71ec03c3c17c151821573114e3b2bb845f1f198d34fb520345fc7`.
Dry-run preparation was inspected before applying. Fresh Mapping953,
Assignment11351 and Package2087 were created under
`mapping_refresh_4744c500c148dc43`. A second apply returned `already_prepared`.
Mapping953 is pending model review and not customer eligible. Mapping649's approval
history remains unchanged; it cannot be reused with the new evidence.

## Actual Remaining Blockers

The independent current-time audit found AWS replacement groups 13->19, 17->20,
18->21 beyond their recorded **7-day** catalog/policy windows. All raw hashes still
match. This is expiration, not detected pricing-code drift or permission to extend
the windows. The 14-day generic price freshness indicator cannot override the
stricter derivation proof. See `freshness_audit_01/summary.md` and `aws_failure.json`.

Work in progress: audited expired-history handling; isolated fresh mapping review
and verified writeback; fresh frozen offline/PostgreSQL verification; current
Decision recomputation and independent model review. Week9-16 remain NO-GO until
their actual checks pass. Full price coverage, cross-provider comparability,
customer authorization, full-chain Eval, and real pilot completion are not claimed.
The owner-deferred real pilot remains separate from technical rehearsal.

## Subsequent Executed Recovery

- The three expired AWS replacement pairs passed retained-fact verification.
  Preview plan `7ab1dec8d584e6e94a5e6754fbae767104ca649605c648c1c5e558674b830a20`
  was applied and replayed idempotently. Receipt SHA256:
  `039ff80c0c564f0ed15915a0a7f89625d29e9bd24dd31d171300660718c700a9`.
  This appended six expiry audit assignments; original prices and approval windows
  were not changed. See `aws_expiry_preview_01`, `aws_expiry_apply_01` and
  `aws_expiry_repeat_01`.
- Current price evidence validation passed: 21 linked records, 11 active domestic
  prices, six expired AWS history rows, four quarantined AWS rows, zero invalid
  supporting chains. No complete overseas price coverage is claimed.
- Mapping953 attempt 01 failed native validation on independently varying input
  and output retention flags. Original artifacts remain failed and local-only.
  The adapter now accepts the independently typed metadata flags only with all
  exact text, hash, native identity, isolation and complete-turn checks unchanged.
  324 focused tests passed and independent code review found no high/medium risk.
  Frozen offline attempt 01 was deliberately interrupted and is not a receipt.
- Fresh mapping attempt 02 completed three independent gpt-6-astra/max sessions.
  Its scope is only `same_service_class`; SKU, price, SLA and performance
  equivalence remain prohibited. The artifact manifest was independently
  revalidated before writeback: SHA256
  `a040b111ed3ca10f90ad7ef584d228f36e7781beb9d4164c45aee10cdb487ef6`.
  Assignment11351/Event11361 was applied once; replay returned `already_applied`.
- The normal EvidencePackage rebuild retained history and superseded old flagged
  packages. Mapping953/Package2106 is the one currently valid scoped package;
  Mapping649 remains historical approved but has no live scoped approval.
  Invalid customer-eligible package flags: zero. This is not customer Decision
  or sales authorization.
- Corrected frozen input SHA256:
  `182ee543da9726c5b660cb2021692ac1852b18057246fee88c9bc74a00d67bf6`.
  PostgreSQL database `_05` completed five migration commands and 14 integration
  tests, with unchanged inputs. Manifest SHA256:
  `632fc38432579c8aa3f5eb90629bbd863fdf1225d756767aafc3a523b7b3e514`.
  Offline frozen attempt 02 passed 3298 tests at 90.8920228790988 percent coverage.
  Manifest SHA256:
  `9878acc859b74183a963491578fae2e6d93931c53fce7acbc4917af2794de5f4`.
  Both sealed receipts were independently revalidated against the current code
  before updating `tasks/verification_receipts.yaml`.

## Final Checkpoint For This Run

The unchanged real Gate checks returned **Week9 GO, Week10 GO, Week11 NO-GO**.
The original prerequisite blockers W11-B001/W11-B002 are cleared. See
`decision_bounded_01/prerequisite_gate.json` and `week11_gate_01.json`.
Week12-16 remain blocked by their prerequisites; no later business development
or release authorization was fabricated.

Decision run36 produced 695 candidates, one eligible and 694 blocked, all internal
only. The fresh eligible result is Decision11279, bound to Mapping953,
EvidencePackage2106 and TCO21. Its local deterministic panel precheck passed with
11 official public evidence records and the executable condition registry.

The attempted external model dispatch was rejected by tool safety review before
process creation. Existing authorization explicitly names official excerpts,
mapping candidates and necessary IDs, but not the Decision/TCO calculation
packet. The owner was asked once for explicit permission covering the sanitized
public-price calculation packet. No alternative execution route was used, no
Decision model call executed, and no Decision approval was written back. Local
readiness correctly remains `current_independent_model_approval_required`.

Remaining actual Week11 blockers:

- W11-B010: no qualifying independently model-approved Decision.
- W11-B011: no customer-eligible Decision output.
- W11-B014: no joined same-scenario customer delivery chain.
- W11-B013: customer-output approval policy is not authorized.

Approving external transmission of this public review packet would not itself
approve customer output, competitive ranking, a release candidate, full-chain
Eval or the owner-deferred real pilot. Complete overseas costs and compatible
cross-vendor comparison also remain outside the proven bounded domestic path.
