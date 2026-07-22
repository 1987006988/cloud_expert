# Test And Coverage Audit

## Verdict

**PARTIAL.** Tests pass, but formatting and coverage gates fail.

## Command Results

| command | result | summary | artifact |
| --- | --- | --- | --- |
| pytest --collect-only -q | PASS | 62 tests collected | cmd_pytest_collect_only.txt |
| ruff format --check . | FAIL | 18 files would be reformatted | cmd_ruff_format_check.txt |
| ruff check . | PASS | All checks passed | cmd_ruff_check.txt |
| mypy src | PASS | 138 source files, no issues | cmd_mypy_src.txt |
| pytest -m "not network" -ra | PASS | 62 passed | cmd_pytest_not_network_ra.txt |
| pytest coverage | PASS_WITH_RISK | 62 passed; coverage 78.6% | cmd_pytest_not_network_coverage.txt |
| validate_source_registry.py | PASS | 74 valid, 4 disabled, 0 errors | cmd_validate_source_registry.txt |
| validate_raw_snapshots.py | PASS | 90 snapshots checked, 0 errors | cmd_validate_raw_snapshots.txt |
| validate_evidence_links.py default DB | FAIL | default DB lacks current tables | cmd_validate_evidence_links_default_db.txt |
| alembic current default DB | FAIL | missing revision 0002_ingestion_runs_and_snapshots | cmd_alembic_current_default_db.txt |
| alembic audit SQLite upgrade/downgrade/reupgrade | PASS | fresh DB and prior-week copies upgrade to 0006 | cmd_alembic_audit_empty_upgrade_head.txt |

## Weak-Test Scan

- `assert True`: no matches.
- `pytest.skip`: no test skip matches; only method names containing `skip` in production summary code.
- `xfail`: no matches.
- `pragma: no cover`: no source/test matches beyond configured coverage settings.
- `coverage: ignore`: no matches.
- `pass`: present mainly in empty Pydantic schema subclasses, not tests.

## Coverage Risk

Overall coverage is **78.6%**. Week6-critical files are weaker: `canonical_service.py` 63%, `unit_standardization.py` 40%, and `schemas/canonical.py` 0%.
