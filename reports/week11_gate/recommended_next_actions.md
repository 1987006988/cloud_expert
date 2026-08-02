# Recommended Next Actions

1. Add controlled human-review import scripts and audit-history validation.
2. Import `D:\download\human_review_completed.zip` into the projection database
   without overwriting pre-review history.
3. Remediate all `reject_reparse` causes, including AWS EC2 memory column shift,
   CPU architecture misclassification, Aliyun ZoneId/name split, SLA extraction,
   and object-storage service-tier/region scope.
4. Re-run parsing, normalization, comparability, mapping, Evidence Package, TCO,
   and decision generation.
5. Add real `DecisionReview` records only after a named reviewer approves the
   regenerated decision results.
6. Re-run Week 11 Gate before implementing sales output.
