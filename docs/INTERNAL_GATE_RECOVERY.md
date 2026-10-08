# Internal Gate Recovery

This implements the owner's 2026-09-30 request to resolve the Week9 -> Week10 ->
Week11 dependency blockage. It does not grant customer or production authority.

## Price Disposition

Retained invalid price rows are not silently deleted, relabeled as approved,
or replaced with estimates. A deterministic quarantine requires an explicit
defect supported by persisted inputs, a preview and exact plan hash, append-only
audit records, and live verification of the receipt on every use. Changed inputs
or receipts return to blocked status. Quarantined rows remain unconsumable.

The price Gate reports current, superseded, quarantined and unresolved rows
separately. Every historical Evidence/source/snapshot relationship still needs
structural integrity. There must be active price data; quarantining everything
does not pass. A disposed historical defect does not establish product coverage,
approve a price, or fill a missing scenario cost. TCO still checks each exact input.

## Current Verification

`tasks/verification_receipts.yaml` selects explicit operational receipts:

- `offline_bundle`: `path` and independently retained `sha256`.
- `postgres`: `manifest_path` and independently retained `sha256`.

The optional `CLOUD_EXPERT_GATE_RECEIPTS` environment variable selects another
explicit context. There is no fallback to old coverage or PostgreSQL reports.
Missing, changed, failed or stale evidence blocks the Gate. The offline runner
binds source/configuration/documentation inputs before and after execution.
The PostgreSQL runner requires an empty named local R011 database, captures all
five real migration commands and integration tests, and binds outputs and code.
No migration round trip runs against the business SQLite database or production.

Example (paths and hashes must come from actual completed runs):

```text
scripts/run_verification_bundle.py --output-dir <new-directory> --execute
scripts/run_postgres_verification.py --output-dir <new-directory>
scripts/check_week09_gate.py
```

PostgreSQL uses `POSTGRES_TEST_DATABASE_URL`; do not commit credentials or put
them in chat. Failed attempts and their incomplete reports must be retained.

## Week11 Scope

`check_week11_gate.py` retains the original customer-facing requirements.
`check_week11_internal_gate.py --candidate-id ... --report-dir ...` evaluates a
separate, explicitly named `WEEK11_INTERNAL_BOUNDED_COST_GATE`.

The internal Gate requires actual Week9 and Week10 GO, a live joined Decision
packet, real official public evidence, and a current controlled writeback from
independent highest-tier primary/adversarial/necessary arbitration review. It
does not accept test fixtures, old Decision approvals, or detached counts of
otherwise unrelated mappings, costs and reviews.

Its only permitted operations are viewing the reviewed bounded cost and
developing an internal cost brief for that exact reviewed scope. It never grants
competitive ranking, SKU/performance/SLA equivalence, customer output, broader
sales eligibility, whole-Week11 completion, or automatic Week12-16 GO. Later
business workflows must validate their own dependencies and claim scope.

The existing Aliyun domestic bounded-cost scenario is a candidate for this route,
not preapproved by this document. A failed or inconclusive model panel stays
failed or inconclusive. Real pilot participation remains deferred by the owner.

## Review Runtime

Different DecisionScenario and PricingScenario identifiers are not evidence of
a mismatch by themselves. The packet exposes their actual foreign-key path,
versions, configuration hash and verified workload constraints. Unspecified
requirements remain unspecified; this binding cannot establish SKU suitability
or competitive equivalence. A model must still independently review that proof.

Ignoring CLI configuration alone is not context isolation. Each new primary,
adversarial or arbitration call requires a fresh private runtime home and empty
working directory, sanitized environment, disabled tools and disabled skill
discovery. Only an opaque local authentication copy may be reused. Authentication
files must not enter the repository, prompts, reports or model payloads.

Native runtime records are local-only audit artifacts, not review inputs. Their
original bytes and hashes are retained under restricted access. Only two exact
authentication-provenance fields in session metadata may be classified as local
metadata after strict complete-runtime validation. Other private fields, secret
patterns, inherited instructions, unknown events, tool calls, context reuse or
an incomplete turn remain blocking. No redaction may remove model identity,
input, completion or isolation evidence to manufacture a passing trace.

The exact observed startup notice that a disabled Code Mode host is unavailable
may be recognized before the turn starts. Arbitrary runtime errors are not
ignored. Compatibility changes require new tests and current verification;
previously rejected runs are never retroactively approved.

The CLI retention `complete` flag is independent for each message; input and
output flags need not agree. Each strict Boolean value must still match its
pinned role-specific metadata profile. Neither value proves completeness:
the full UTF-8 prompt, duplicated input event, response, final completion,
hashes, isolated identity and single-turn ordering must all match exactly.
Truncation, extra context and missing completion remain blocking for every flag
combination.

## History

All run directories are separate. Explicit Decision report directories also
receive their own review-sample CSV, preserving the prior shared sample file.
Old prices, failed reviews, rejected facts and failed test reports stay visible.
Internal GO and the original customer Gate are always reported as separate states.
