# Automated Repair Policy

Deterministic failures and `model_rejected_reparse` are repair tasks, not
approval opportunities. Cluster by parser rule, field semantics, provider,
product, snapshot, and source section before proposing code changes. Repair
the parser or normalizer, add a synthetic regression fixture, rerun the
immutable raw snapshot, then rebuild normalization, comparability, mapping,
Evidence Package, price/TCO, and Decision descendants in order.

Never directly edit a parsed or normalized fact to bypass the originating
parser. Preserve raw snapshots, official excerpts, old review records, and old
derived runs. Report impact count before applying; compare before/after hashes
and evidence references. If source evidence is absent or conflicting, retain
`model_inconclusive` or `model_blocked`.

Week14 has **not** created RepairTask records or executed a new parser repair
batch. The 10,332 deterministically blocked assignments remain open for root
cause clustering and source-backed remediation.
