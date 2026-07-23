# R008 Human Review Gate Waiver

Generated at: 2026-07-23T00:00:00+08:00

Waiver status: **waived_by_owner**

## Owner Instruction

The project owner instructed Codex in this task thread:

```text
先把人工审核的豁免了，执行后续几周的任务
```

This is recorded as a governance waiver for the Week 7 admission blocker
`R008_review_queue_policy`.

## Scope

The waiver allows internal engineering work for Week 7, Week 8, and Week 9 to
proceed through their gates. It does not mean the review queues were manually
resolved, and it does not make pending-review facts customer eligible.

## Preserved Review State

The previous review package remains the source of human review work:

```text
D:\审核文件
```

Known queue counts at the time of waiver:

| Queue | Rows |
| --- | ---: |
| ReviewItem open/in_review | 1441 |
| NormalizedSpecification pending_review | 678 |
| Scope mismatch review | 0 |
| Comparability blockers | 103 |
| DataQualityIssue open/in_review | 0 |

## Controls

- Automatically generated Week 7 mapping candidates must remain `candidate` or
  `pending_review`.
- Codex must not mark candidates or mappings as `approved`.
- Week 8 customer-output eligibility must fail for packages containing
  pending-review mapping or evidence.
- Week 9 TCO output must remain internal and non-binding, and must not use
  missing prices as zero.

## Follow-Up

The review package should still be processed later. Reviewer decisions must be
applied as a separate, auditable change before any customer-facing comparison,
sales output, or committed product equivalence claim is allowed.
