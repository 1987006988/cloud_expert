import json
import subprocess
import sys
from pathlib import Path

import pytest

from cloud_expert.ingestion.content.inspector import inspect_content
from cloud_expert.ingestion.content.pdf import inspect_pdf


def test_content_inspectors_cover_invalid_json_and_pdf() -> None:
    _formatted, metadata = inspect_content("application/json", b"{bad json")
    assert metadata["json_parse_success"] is False
    with pytest.raises(ValueError):
        inspect_pdf(b"not a pdf")


def test_validate_source_registry_cli() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_source_registry.py"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    summary = json.loads(result.stdout)
    assert summary["valid_sources"] >= 3


def test_validate_raw_snapshots_cli_empty_dir() -> None:
    raw_dir = Path("test_outputs") / "empty_raw_cli"
    raw_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "scripts/validate_raw_snapshots.py", "--raw-dir", str(raw_dir)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    summary = json.loads(result.stdout)
    assert summary["snapshots_checked"] == 0
