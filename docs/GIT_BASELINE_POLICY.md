# Git Baseline Policy

Stage 1 remediation establishes provenance from the first auditable repository
state forward. It does not reconstruct weekly history that was not committed at
the time.

## Current Baseline

- Branch: `main`
- Remote: `git@github.com:1987006988/cloud_expert.git`
- Baseline commit: `65ab21a chore: baseline week01-06 audit`
- Baseline tags:
  - `audit-week01-06-baseline`
  - `audit-week06-baseline`

Both tags point to the same pre-remediation audit baseline commit. This is
intentional: it records the state that the Week 1-6 independent audit reviewed.

## Rules

- Do not rewrite the baseline commit to pretend that earlier weekly commits
  existed.
- Commit remediation work after the baseline as ordinary forward history.
- Keep generated SQLite databases, raw snapshots, local coverage files, and
  temporary outputs ignored unless a report is deliberately curated for review.
- Before claiming a milestone is reproducible, record the commit hash, tag or
  branch, exact validation commands, and any environment blockers.
- Do not push tags or commits automatically unless the user asks for a push.

## Tracked And Ignored Artifacts

The repository may track curated reports such as normalization coverage outputs
or remediation summaries. It must not track local development databases, raw
snapshot bytes, `.coverage`, temporary files, or generated acceptance SQLite
databases.

Stage 1 removed the stale tracked audit `coverage.json` from Git and left the
local generated file ignored.
