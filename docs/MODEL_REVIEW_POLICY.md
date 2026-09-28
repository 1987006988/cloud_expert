# Model Review Policy

The project owner requested model review of the remaining Week 11 queue. The
`run_model_review.py` command records an evidence-aware, repeatable policy
assessment in `model_review_run` and `model_review_finding`.

Each finding stores the subject ID, verdict, reason code, rationale, evidence
IDs, and an input hash. A run stores the policy version, reviewer identity,
input fingerprint, and summary. Running against unchanged inputs is idempotent;
new inputs create a new run while previous findings remain available.

The current policy evaluates:

- all MappingCandidate rows;
- all unresolved ReviewItem rows;
- all pending ComparabilityAssessment rows;
- all CandidateDecisionResult rows, including prior runs.

The agent reviewed the classification rules and source-backed samples before
running them across the queue. These are policy-based model assessments, not
individual manual source-page inspections. `requires_source_verification` and
`reparse_required` are real unresolved outcomes. They must not be counted as
accepted facts.

Model findings never set `human_reviewed`, `internally_approved`,
`customer_eligible`, or any customer output level. They do not replace the
separate `HumanReviewDecision`, `MappingReview`, or `DecisionReview` records.
Cross-market mappings are limited to internal research even if another process
marks their review status as human-reviewed.

The Week 11 customer-output Gate continues to require real human review and
customer-eligible evidence and decisions. If the project owner authorizes an
internal engineering waiver, that must be a separate, explicit gate with an
`internal_only` output restriction; it must not rename model review as human
review or silently change the customer Gate.
