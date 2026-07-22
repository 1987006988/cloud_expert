# Week 7 Recommended Next Actions

Generated at: 2026-07-22T23:41:11+08:00

## Required Before Week 7

1. Complete the manual review package in `D:\审核文件`.
2. Record reviewer identity, review date, and decision source for the R008 queue.
3. Apply approved, corrected, rejected, or waived decisions back into the project database and governance records.
4. Regenerate the R008 review package or queue summary to prove no blocking review items remain.
5. Update `tasks/remediation_backlog.yaml`, `docs/PROJECT_STATE.md`, and `docs/SESSION_HANDOFF.md` only after the review decisions are applied or formally waived.
6. Rerun the Week 7 gate and keep the generated gate evidence.

## Acceptance Conditions For R008 Closure

R008 can be closed only when one of the following is true:

| Path | Required Evidence |
| --- | --- |
| Human review completed | Reviewer-approved decision records are present and applied to the database; open review counts are reduced to a non-blocking state; comparability blockers are regenerated from the reviewed data. |
| Formal waiver | A named project owner records a dated waiver explaining why Week 7 may proceed despite unresolved review rows, and the waiver is committed to the repository. |

## Then Start Week 7

After the gate changes to `WEEK7_GATE=GO`, implementation can proceed in this
order:

1. Add product mapping and candidate data models.
2. Add deterministic cross-vendor matching rules.
3. Generate candidate mappings from reviewed normalized data.
4. Export mapping review queues for human approval.
5. Add tests and evidence reports for every mapping rule and candidate source.

Until then, product mapping implementation should remain untouched.
