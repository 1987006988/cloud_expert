# R008 Waiver Checkpoint

Date: 2026-07-23

`R008_review_queue_policy` was changed from `pending_human_review` to
`waived_by_owner` based on explicit project-owner instruction in the Codex task
thread.

The waiver only opens internal Week 7-9 engineering execution. Pending review
rows remain pending and must not be treated as customer-eligible facts.

Evidence:

- `reports/remediation/r008_waiver/waiver_record.md`
- `reports/remediation/r008_waiver/waiver_results.json`
