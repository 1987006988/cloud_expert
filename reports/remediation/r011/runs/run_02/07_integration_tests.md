# Integration Tests

Generated at: 2026-07-22T23:02:12+08:00

## PostgreSQL Marker

Command:

```powershell
pytest -m postgres -ra
```

Result:

```text
collected 71 items / 65 deselected / 6 selected
tests\integration\test_postgres_r011.py ...... [100%]
6 passed, 65 deselected
```

## Integration Directory

Command:

```powershell
pytest tests\integration -m "not network" -ra
```

Result:

```text
collected 6 items
tests\integration\test_postgres_r011.py ...... [100%]
6 passed
```

## Full Non-Network Suite

Command:

```powershell
pytest -m "not network" -ra
```

Result:

```text
collected 71 items
71 passed
```

## Coverage

Command:

```powershell
pytest -m "not network" --cov=cloud_expert --cov-report=term-missing --cov-report=json:reports\remediation\r011\runs\run_02\coverage.json
```

Result:

```text
71 passed
TOTAL coverage: 79%
```

Coverage remains below the separate 85% remediation target. That keeps R009
open, but does not block R011 because PostgreSQL validation and R011-specific
tests passed.

## Quality Commands

| Command | Result |
| --- | --- |
| `ruff format .` | passed, 197 files unchanged |
| `ruff format --check .` | passed, 197 files already formatted |
| `ruff check .` | passed |
| `mypy src scripts` | passed, 172 source files |
