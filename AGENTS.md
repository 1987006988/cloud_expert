# Agent Instructions

This repository is evidence-first. Do not add real cloud product facts unless
they can be traced to a `SourceDocument` and `Evidence` record.

The owner authorized execution of the Week 11-16 closure checklist on
2026-09-30, including parallel work on independent packages. The original
Week 1 database-only restriction is historical, not the active phase.
Use docs/WEEK11_16_CLOSURE_CHECKLIST.md and tasks/active_task.yaml for scope.

- Preserve existing changes, immutable source snapshots and review history.
- Execute prerequisite remediation and Week14 review migration before gated
  sales or UI development. Never bypass a failed dependency Gate.
- Real facts and prices require official SourceDocument and Evidence records.
  Synthetic fixtures must stay clearly labeled and cannot approve real data.
- Use deterministic prechecks, independent highest-tier model primary and
  adversarial review, and arbitration for disagreements. Do not require
  per-record human approval or falsely relabel model reviews as human reviews.
- Only owner-authorized official excerpts, candidate data and necessary
  identifiers may be transferred for model review. Never transfer credentials,
  account-sensitive responses, personal discounts or customer-sensitive data.
- Price inquiries must be read-only. Do not create orders or cloud resources.
- Default deployment work to an isolated release candidate. Real production
  writes, migrations, deployments and traffic changes need explicit approval.
- Actual internal pilot participants and real-user feedback are deferred by
  the owner; technical rehearsals cannot be reported as real pilot completion.
- Parallel workers must have disjoint file ownership. Only the coordinating
  agent may write the shared business database or update aggregate Gate state.

