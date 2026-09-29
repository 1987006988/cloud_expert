# Model Review Policy

The owner has authorized model review for internal engineering work. Historical
human decisions keep their original labels. New model decisions must never be
written as `human_reviewed`.

The historical Week11 pilot chain was:

1. `run_model_review.py` makes a deterministic, evidence-aware precheck. It is
   not an individual model opinion or an approval.
2. Two independent `gpt-6-astra` sessions inspect each subject and submit
   structured primary and adversarial manifests with the same input hash.
3. `arbitrate_model_reviews.py` verifies subject hashes, evidence IDs, session
   separation, and precheck linkage, then records append-only findings. A
   disagreement is resolved conservatively. Conditional approval is internal
   only and does not waive an unmet condition.
4. `apply_model_review_actions.py` may write back an explicit dual-model
   rejection, with a model-labelled `MappingReview` or `DecisionReview` record.
   Reparse and insufficient-evidence findings remain unresolved. No script
   converts them to accepted product facts.
5. Downstream evidence, TCO, and decisions are recomputed, tests run, and Gate
   reports are regenerated. Old runs and source snapshots remain available.

The first individual panel reviewed six subjects. Arbitration rejected two
and required reparse on four. It approved none. The remaining subjects in that
historical precheck were **not** individually reviewed by both models. A
deterministic classification is not a model-review substitute. The current
Week14 precheck contains 11,342 findings; its queue migration preserves this
distinction. See `docs/MODEL_REVIEW_ARCHITECTURE.md` and
`docs/MODEL_SELECTION_POLICY.md` for the new overlay and runtime policy.

`ModelReviewRun.summary_json.model_origin_attested_by_tool` is false because
the manifest importer cannot cryptographically verify model provenance. The
recorded session IDs and separate manifests are audit leads, not proof supplied
by the database. Customer eligibility remains closed until the full dependency
chain and the explicitly configured customer-output policy pass. The internal
development authorization does not itself authorize customer materials.

The later Week14 authorized pilot reviewed mapping candidate 415 in isolated
primary, adversarial, and adjudication sessions. Its final result is
`model_inconclusive` because the cited SKU rows do not prove product-level
service-class equivalence. An independent nonapproval importer wrote one
model-labelled assignment transition and audit event, not a business mapping
approval. Earlier failed attempts and a corrected consensus result are
preserved under `reports/model_review/week14_pilot/`.
