# Test Results

Final Stage 1 checks:

| Command | Result |
| --- | --- |
| `ruff format .` | passed |
| `ruff check .` | passed |
| `mypy src scripts` | passed, 171 source files |
| `pytest --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports/remediation/stage1/coverage.json` | passed, 65 tests |
| `alembic current` | `0006_week06_canonical_normalization (head)` |
| `alembic heads` | `0006_week06_canonical_normalization (head)` |
| `scripts/validate_default_database.py` | passed |
| `scripts/validate_normalized_evidence.py` | passed |
| `scripts/validate_week06_projection.py` | passed |

Coverage total: 79%.

Coverage output: `coverage.json`.
