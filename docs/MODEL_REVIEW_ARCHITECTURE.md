# Model Review Architecture

Week14 runs in `review_migration` mode because Week9/10 are GO and Week13 is
NO-GO. Alembic 0014 adds an overlay queue instead of changing old human review
rows. `model_review_assignment` links each deterministic finding to a target,
input hash, preserved prior status, evidence IDs, and new review state.
`model_review_audit_event` records every initial transition. Both tables use
restrictive foreign keys; a downgrade refuses to discard nonempty history.

The current precheck run created 11,342 assignments. After one authorized
pilot, the states are 1,009 `pending_model_review`, 10,332
`blocked_by_deterministic_check`, and one `model_inconclusive`. Only the last
is an individual Week14 model decision. Historical human and prior model
records are untouched. A second migration run created zero new rows.

The mapping pilot prepares an immutable input from the candidate,
its precheck hash, official Evidence excerpts, SourceDocument, and verified raw
snapshot hashes. Primary, adversarial, and conditional adjudication stages use
separate ephemeral CLI sessions with separate prompts. Strict Pydantic schemas
reject extra fields, invalid decisions, out-of-range confidence, missing
approval citations, and evidence IDs outside the input. Deterministic blockers
take precedence over model output. The pilot never writes a business approval.
Input is sent over UTF-8 stdin rather than a Windows command-line argument;
failed attempts get new directories. A separate controlled command can apply
only a validated nonapproval to `model_review_assignment` with an append-only
`model_review_audit_event`. It verifies the current input hash, Evidence set,
stage files, distinct sessions, and conservative consensus before commit.
`model_inconclusive` remains an unresolved Gate state.

The owner later explicitly authorized this narrow transfer, superseding the
earlier rejection for the allowed payload only. Candidate 415 completed all
three model stages and remained inconclusive because its SKU-row excerpts do
not substantiate a product-level mapping. The original stage outputs and a
consensus-correction record are preserved in the pilot report. The system still
lacks a validated batch caller, per-target review cache, persistent stage
records, parser repair-task table, and controlled approval writeback. Those
gaps, the remaining queues, and incomplete Eval keep Week14 NO-GO.
