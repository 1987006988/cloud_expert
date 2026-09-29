# Independent Price Code Review

Date: 2026-09-30 (Asia/Shanghai).
Scope: AWS replacement lifecycle, current-price consumption and price inventory
validation. This is code review, not a business model-review panel, fact approval,
customer authorization or release Gate.

## Finding and Resolution

P2: reading expired ORM identifiers or lazy relationships before the clean-session
guard could trigger SQLAlchemy autoflush during nominally read-only validation.

Resolution:

- The provider/rule classifier suppresses autoflush on its bound session.
- Current/disposition entry points reject new, dirty or deleted state before
  loading any price properties.
- The replacement resolver obtains the persistent identity through SQLAlchemy
  inspection without loading an expired identifier.
- Pending changes remain pending; no implicit commit or flush is permitted.

Coordinator regression receipt: `price_dispatch_05/junit.xml`, 27 passes.
Replacement-owner focused regression: 41 passes, with dirty/new/deleted cases.
Independent reviewer reported 9/9 pure-memory checks passing across three entry
points and three pending-state variants, with zero SQL and zero flush attempts.
The reviewer performed no source edits or business database writes and confirmed
the P2 closed. Its report is retained in the coordinating conversation; the 9
checks are not represented as a separately sealed full-suite JUnit run.

No other confirmed high-risk receipt, current policy, tier-group or legacy/v2
admission bug was identified within this review's bounded scope. This does not
assert that the entire repository is defect-free. Full offline verification,
live price evidence validation and PostgreSQL integration remain separate checks.

## Related Actual Data Checks

All three replacements were applied and retried through the coordinator CLI:
13 -> 19, 17 -> 20 and 18 -> 21. Repeat runs added zero Evidence and price rows.
Current validation is recorded in `price_evidence_replacement_03.json`: 21/21
structural evidence/source links, three verified superseded records, and four
unresolved AWS records (1, 14, 15, 16). Overall price validation remains false.
Old rows, raw documents and review history were retained. No model approval or
complete AWS TCO was created by this replacement operation.
