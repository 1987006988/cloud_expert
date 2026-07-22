# Week 8 Unresolved Blockers

Generated at: 2026-07-22T23:46:13+08:00

## Blocking Items

| ID | Status | Blocks Week 8 | Reason |
| --- | --- | --- | --- |
| W8-B001-week7-gate | open | Yes | Latest Week 7 gate report records `WEEK7_GATE=NO-GO`. |
| W8-B002-r008-human-review | pending_human_review | Yes | R008 review decisions from `D:\审核文件` have not been applied or formally waived. |
| W8-B003-mapping-rules | missing | Yes | `MappingRuleSet` model/table and `validate_mapping_rules.py` are absent. |
| W8-B004-mapping-candidates | missing | Yes | `MappingCandidate` model/table is absent and no candidate rows exist. |
| W8-B005-field-comparisons | missing | Yes | `MappingFieldComparison` model/table is absent. |
| W8-B006-mapping-evidence | missing | Yes | Week 7 mapping evidence validation script and quality report are absent. |
| W8-B007-idempotency | missing | Yes | Week 7 mapping idempotency validation script is absent. |

## Current Counts

| Item | Count |
| --- | ---: |
| `product_mapping` rows | 0 |
| `mapping_candidate` table | absent |
| `mapping_rule_set` table | absent |
| `mapping_field_comparison` table | absent |
| Open/in-review ReviewItem rows awaiting human governance | 1441 |
| NormalizedSpecification rows pending review | 678 |
| Comparability blockers awaiting review context | 103 |

## Non-Blocking Checks That Passed

| Check | Result |
| --- | --- |
| Ruff format check | Passed; 203 files already formatted. |
| Ruff lint | Passed. |
| mypy `src scripts` | Passed; 173 source files checked. |
| Pytest non-network suite | Passed; 83 passed / 6 skipped. |
| Pytest PostgreSQL marker suite | Passed; 6 passed with live PostgreSQL URL. |
| Default database validation | Passed; default SQLite is at Alembic head. |
| Week 6 projection validation | Passed; `valid=true`. |
| Normalized evidence validation | Passed; 10172 rows, 0 hash mismatches. |

## Stop Condition

No Week 8 evidence package code, models, migrations, reports, or CLI tools may
be implemented until these blockers are closed.
