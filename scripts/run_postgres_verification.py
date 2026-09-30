"""Capture real migration and integration receipts on an EMPTY local R011 database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from cloud_expert.evals.verification_run import snapshot_inputs
from cloud_expert.quality.verification_receipts import (
    EXPECTED_HEAD,
    EXPECTED_POSTGRES_TEST_IDS,
    EXPECTED_PREVIOUS,
)


def validate_test_target(value: str) -> None:
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1"}
        or not (url.database or "").startswith("cloud_expert_r011_")
        or url.query
    ):
        raise ValueError("An isolated local R011 PostgreSQL database is required")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    value = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
    validate_test_target(value)
    engine = create_engine(value)
    try:
        if inspect(engine).get_table_names(schema="public"):
            raise ValueError("Refusing migration round trips on a nonempty database")
    finally:
        engine.dispose()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot_inputs(ROOT)["sha256"]
    environment = dict(os.environ, DATABASE_URL=value, PYTHONUTF8="1")
    steps = (
        ("fresh_upgrade", ["-m", "alembic", "upgrade", "head"]),
        ("downgrade_one", ["-m", "alembic", "downgrade", "-1"]),
        ("reupgrade_one", ["-m", "alembic", "upgrade", "head"]),
        ("downgrade_base", ["-m", "alembic", "downgrade", "base"]),
        ("reupgrade_base", ["-m", "alembic", "upgrade", "head"]),
        (
            "pytest",
            [
                "-m",
                "pytest",
                "tests/integration",
                "-m",
                "postgres",
                "-q",
                f"--basetemp={output / 'pytest_temp'}",
                f"--junitxml={output / 'junit.xml'}",
            ],
        ),
    )
    receipts: dict[str, Any] = {}
    for name, arguments in steps:
        path = output / f"{name}.log"
        with path.open("xb") as log:
            try:
                completed = subprocess.run(
                    [sys.executable, *arguments],
                    cwd=ROOT,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                    check=False,
                )
                code = completed.returncode
            except subprocess.TimeoutExpired:
                code = 124
        receipts[name] = {
            "path": str(path),
            "returncode": code,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if code:
            break
    after = snapshot_inputs(ROOT)["sha256"]
    junit = output / "junit.xml"
    payload = {
        "version": "local-postgres-verification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "repository_input_sha256": before,
        "input_sha256_before": before,
        "input_sha256_after": after,
        "inputs_unchanged": before == after,
        "expected_test_ids": sorted(EXPECTED_POSTGRES_TEST_IDS),
        "expected_head": EXPECTED_HEAD,
        "expected_previous": EXPECTED_PREVIOUS,
        "junit": {
            "path": str(junit),
            "returncode": receipts.get("pytest", {}).get("returncode", -1),
            "sha256": hashlib.sha256(junit.read_bytes()).hexdigest() if junit.exists() else None,
        },
        "migrations": {name: receipt for name, receipt in receipts.items() if name != "pytest"},
        "commands": receipts,
        "full_chain_eval": False,
        "business_database_touched": False,
    }
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    successful = len(receipts) == 6 and all(r["returncode"] == 0 for r in receipts.values())
    print(
        json.dumps(
            {
                "commands_succeeded": successful,
                "inputs_unchanged": before == after,
                "manifest": str(manifest),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "requires_receipt_validation": True,
            },
            indent=2,
        )
    )
    return 0 if successful and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
