# Eval Architecture

`cloud_expert_v1` currently contains 37 unique, synthetic deterministic cases.
They invoke real domain functions for source URL safety, market-mode mapping,
price freshness, TCO line arithmetic and missing-price handling, model-output
validation/consensus, and Decision hard blocks. Cases have explicit inputs,
expected outputs, type, category, severity, and provider/product/market labels.
The runner records each actual result and critical failure; it does not mark
unmeasured metrics as passing.

This is an initial subset, **not** the requested 400-case full-chain suite.
Parsing, normalization, comparability, Evidence Packages, Sales Artifact,
UI, live smoke, and Model Judge are not evaluated here. Model Judge is not run
while external review-data transfer is unapproved. The Gate checks
`full_chain_coverage=false` and remains NO-GO even if every current case passes.

Run with `python scripts/run_eval_suite.py --suite cloud_expert_v1`, then
`python scripts/generate_eval_report.py --suite cloud_expert_v1`. Results live
in `reports/evals/`; their synthetic nature must be preserved in any summary.
