# Remediation Stage 2 Summary

Generated at: 2026-07-22T23:28:26+08:00

Stage 2 verdict: **ENGINEERING COMPLETE, HUMAN REVIEW PENDING**.

`WEEK7_GATE=NO-GO`

## Closed Engineering Items

| Item | Status | Evidence |
| --- | --- | --- |
| R005 | complete | Canonical seed metadata now includes semantic, lifecycle/deprecation, evidence, review-policy, and comparability governance fields. |
| R006 | complete | Field matrices regenerated with semantic/unit/scope/qualifier/evidence/comparability/lifecycle/review-policy status columns. |
| R007 | complete | Comparability assessment now blocks on pending review, unit mismatch, qualifier mismatch, scope mismatch, and market-scope mismatch. |
| R009 | complete | Coverage gate raised from 79% to 85%. |

## Human Review Queue

R008 is routed but not closed. Review package:

`D:\审核文件`

| Queue | Rows |
| --- | ---: |
| ReviewItem open/in_review | 1441 |
| NormalizedSpecification pending_review | 678 |
| Scope mismatch review | 0 |
| Comparability blockers | 103 |
| DataQualityIssue open/in_review | 0 |

## Refreshed Week 6 Metrics

| Metric | Count |
| --- | ---: |
| Canonical field definitions | 38 |
| Normalization rules | 40 |
| Normalized specifications | 10172 |
| Comparability assessments | 116 |
| Machine-extracted normalized rows | 9494 |
| Pending-review normalized rows | 678 |
| Scope mismatch warnings | 0 |
| Comparable assessments | 13 |
| Partial assessments | 64 |
| Not-comparable assessments | 37 |
| Needs-review assessments | 2 |
| Missing normalized evidence links | 0 |
| Average normalization quality score | 0.9798 |

## Validation

| Command | Result |
| --- | --- |
| `ruff check .` | passed |
| `ruff format --check .` | passed |
| `mypy src scripts` | passed, 173 source files |
| `pytest -m "not network" --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports/remediation/stage2/coverage.json` | passed, 83 passed / 6 skipped, 85% coverage |
| `scripts/validate_canonical_definitions.py` | passed, 38 fields / 40 mappings / 0 errors |
| `scripts/validate_canonical_units.py` | passed, 10172 checked / 0 errors |
| `scripts/validate_value_qualifiers.py` | passed, no unknown qualifiers |
| `scripts/validate_specification_scopes.py --summary-only` | passed, no unknown scopes / 0 mismatch warnings |
| `scripts/validate_normalized_evidence.py` | passed, 10172 rows / 0 missing links / 0 hash mismatches |
| `scripts/validate_week06_projection.py` | passed, valid=true |

## Remaining Gate

Week 7 product mapping must not start until reviewer decisions from
`D:\审核文件` are applied to the database or explicitly waived.
