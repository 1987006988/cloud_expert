"""Synthetic receipts only; no PostgreSQL connection or real-data approval."""

from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import yaml

from cloud_expert.evals import verification_run
from cloud_expert.quality.verification_receipts import (
    EXPECTED_HEAD,
    EXPECTED_POSTGRES_TEST_IDS,
    EXPECTED_PREVIOUS,
    MIGRATION_STEPS,
    CommandReceipt,
    MigrationStep,
    ReceiptResult,
    read_gate_receipts,
    read_offline_bundle,
    read_postgres_receipts,
)

TEST_ID = "tests.integration.test_postgres_synthetic::test_synthetic"
JUNIT = (
    '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
    '<testcase classname="tests.integration.test_postgres_synthetic" name="test_synthetic"/>'
    "</testsuite></testsuites>"
)


@pytest.fixture
def sealed_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str]:
    repo = tmp_path / "synthetic_repo"
    for directory in verification_run.INPUT_DIRS:
        (repo / directory).mkdir(parents=True)
    for name in verification_run.REQUIRED_FILES:
        (repo / name).write_text("# synthetic\n", encoding="utf-8")
    (repo / "src/cloud_expert").mkdir()
    (repo / "src/cloud_expert/synthetic.py").write_text("value = 1\n", encoding="utf-8")
    summary = {
        "covered_lines": 90,
        "num_statements": 100,
        "missing_lines": 10,
        "covered_branches": 0,
        "num_branches": 0,
        "missing_branches": 0,
        "percent_covered": 90,
    }

    def synthetic_runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        output = Path(kwargs["cwd"]).parent
        if "pytest" in argv:
            (output / "junit.xml").write_text(JUNIT, encoding="utf-8")
            (output / "coverage.json").write_text(
                json.dumps(
                    {
                        "meta": {"branch_coverage": True},
                        "files": {"src/cloud_expert/synthetic.py": {"summary": summary}},
                        "totals": summary,
                    }
                ),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(argv, 0, b"synthetic stdout", b"")

    monkeypatch.setattr(subprocess, "run", synthetic_runner)
    bundle = tmp_path / "synthetic_bundle"
    result = verification_run.run_verification(repo, bundle, execute=True)
    assert result["passed"]
    return repo, bundle, result["manifest_sha256"]


def test_sealed_reader_reuses_real_verifier(sealed_bundle: tuple[Path, Path, str]) -> None:
    repo, bundle, sha = sealed_bundle
    result = read_offline_bundle(bundle, expected_manifest_sha256=sha, current_repo=repo)
    assert result["valid"] and result["current_code_verified"]
    assert result["code_fingerprint_status"] == "current"
    assert result["metrics"] == {"tests": 1, "coverage_percent": 90.0}
    assert result["provenance"]["expected_manifest_sha256"] == sha
    assert result["full_chain_eval"] is False
    assert result["provenance"]["verification"]["postgres_executed"] is False


@pytest.mark.parametrize("sha", ["", "not-a-hash", "0" * 64])
def test_external_anchor_required(sealed_bundle: tuple[Path, Path, str], sha: str) -> None:
    repo, bundle, _ = sealed_bundle
    result = read_offline_bundle(bundle, expected_manifest_sha256=sha, current_repo=repo)
    assert not result["valid"] and not result["current_code_verified"]
    assert result["errors"]


def test_tampered_artifact_rejected(sealed_bundle: tuple[Path, Path, str]) -> None:
    repo, bundle, sha = sealed_bundle
    (bundle / "junit.xml").write_text(JUNIT.replace('tests="1"', 'tests="9"'), encoding="utf-8")
    assert not read_offline_bundle(bundle, expected_manifest_sha256=sha, current_repo=repo)["valid"]


def test_stale_checkout_does_not_rewrite_history(sealed_bundle: tuple[Path, Path, str]) -> None:
    repo, bundle, sha = sealed_bundle
    (repo / "src/cloud_expert/new.py").write_text("changed = True\n", encoding="utf-8")
    result = read_offline_bundle(bundle, expected_manifest_sha256=sha, current_repo=repo)
    assert result["valid"] and not result["current_code_verified"]
    assert result["code_fingerprint_status"] == "stale"
    assert "stale_code_fingerprint:historical_receipt_only" in result["warnings"]


def test_unreadable_current_checkout_not_certified(sealed_bundle: tuple[Path, Path, str]) -> None:
    repo, bundle, sha = sealed_bundle
    result = read_offline_bundle(bundle, expected_manifest_sha256=sha, current_repo=repo / "absent")
    assert result["valid"] and not result["current_code_verified"]
    assert result["code_fingerprint_status"] == "unavailable"


def test_missing_bundle_does_not_fall_back(sealed_bundle: tuple[Path, Path, str]) -> None:
    repo, bundle, sha = sealed_bundle
    result = read_offline_bundle(
        bundle / "missing", expected_manifest_sha256=sha, current_repo=repo
    )
    assert not result["valid"]
    assert result["provenance"]["bundle_dir"].endswith("missing")


def _log(direction: str, transitions: list[tuple[str, str]]) -> str:
    return "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.\n" + "\n".join(
        f"INFO  [alembic.runtime.migration] Running {direction} {a} -> {b}, Synthetic migration."
        for a, b in transitions
    )


@pytest.fixture
def pg_receipts(tmp_path: Path) -> tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]]:
    junit = tmp_path / "synthetic_junit.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    migrations = {}
    for step in MIGRATION_STEPS:
        if step == "downgrade_one":
            transitions = [("synthetic_head", "synthetic_previous")]
        elif step == "reupgrade_one":
            transitions = [("synthetic_previous", "synthetic_head")]
        elif step == "downgrade_base":
            transitions = [("synthetic_head", "synthetic_previous"), ("synthetic_previous", "")]
        else:
            transitions = [("", "synthetic_previous"), ("synthetic_previous", "synthetic_head")]
        direction = "downgrade" if step.startswith("downgrade") else "upgrade"
        path = tmp_path / f"{step}.log"
        path.write_text(_log(direction, transitions), encoding="utf-8")
        migrations[step] = CommandReceipt(path, 0)
    return CommandReceipt(junit, 0), migrations


def _read_pg(receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]]) -> ReceiptResult:
    junit, migrations = receipts
    return read_postgres_receipts(
        junit,
        migrations=migrations,
        expected_test_ids=frozenset({TEST_ID}),
        expected_head="synthetic_head",
        expected_previous="synthetic_previous",
    )


def test_postgres_receipt_provenance_and_limits(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]],
) -> None:
    result = _read_pg(pg_receipts)
    assert result["valid"] and result["metrics"]["tests"] == 1
    assert result["full_chain_eval"] is False and not result["current_code_verified"]
    assert result["code_fingerprint_status"] == "not_recorded"
    assert result["provenance"]["execution_authenticated"] is False
    assert len(result["provenance"]["junit"]["sha256"]) == 64
    assert set(result["provenance"]["migrations"]) == set(MIGRATION_STEPS)


@pytest.mark.parametrize(
    "xml",
    [
        "<bad",
        "<testsuites/>",
        JUNIT.replace('tests="1"', 'tests="2"'),
        JUNIT.replace('failures="0"', 'failures="1"'),
        JUNIT.replace('errors="0"', 'errors="1"'),
        JUNIT.replace('skipped="0"', 'skipped="1"'),
        JUNIT.replace("/>", "><skipped/></testcase>"),
        JUNIT.replace("/>", "><failure/></testcase>"),
        JUNIT.replace("/>", "><error/></testcase>"),
        JUNIT.replace("test_postgres_synthetic", "test_sqlite_synthetic"),
        JUNIT.replace('name="test_synthetic"', 'name="test_different"'),
        JUNIT.replace("<testsuites>", '<testsuites tests="2">'),
        JUNIT.replace("<testsuites>", '<testsuites failures="1">'),
        '<!DOCTYPE testsuites [<!ENTITY fake "synthetic">]>' + JUNIT,
        JUNIT.replace(
            "</testsuite>",
            '<testcase classname="tests.integration.test_postgres_synthetic" name="test_synthetic"/></testsuite>',
        ).replace('tests="1"', 'tests="2"'),
    ],
)
def test_invalid_junit_never_passes(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]], xml: str
) -> None:
    pg_receipts[0].path.write_text(xml, encoding="utf-8")
    assert not _read_pg(pg_receipts)["valid"]


@pytest.mark.parametrize("step", MIGRATION_STEPS)
def test_every_migration_is_required(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]], step: MigrationStep
) -> None:
    del pg_receipts[1][step]
    assert not _read_pg(pg_receipts)["valid"]


@pytest.mark.parametrize("returncode", [1, -1, True])
def test_nonzero_or_boolean_exit_status_rejected(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]], returncode: int
) -> None:
    junit, migrations = pg_receipts
    assert not _read_pg((CommandReceipt(junit.path, returncode), migrations))["valid"]
    migrations["reupgrade_one"] = CommandReceipt(migrations["reupgrade_one"].path, returncode)
    assert not _read_pg(pg_receipts)["valid"]


@pytest.mark.parametrize(
    "replacement",
    [
        "",
        "INFO Context impl PostgresqlImpl.",
        _log("upgrade", [("synthetic_previous", "wrong_head")]),
        _log("downgrade", [("synthetic_previous", "synthetic_head")]),
        _log("upgrade", [("synthetic_previous", "synthetic_head")]) + "\nERROR failed commit",
        _log("upgrade", [("synthetic_previous", "synthetic_head")]).replace(
            "PostgresqlImpl", "SQLiteImpl"
        ),
    ],
)
def test_migration_failure_or_wrong_target_rejected(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]], replacement: str
) -> None:
    pg_receipts[1]["reupgrade_one"].path.write_text(replacement, encoding="utf-8")
    assert not _read_pg(pg_receipts)["valid"]


def test_missing_report_never_uses_neighbor(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]],
) -> None:
    junit, migrations = pg_receipts
    assert not _read_pg((CommandReceipt(junit.path.with_name("missing.xml"), 0), migrations))[
        "valid"
    ]


def test_duplicate_paths_rejected(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]],
) -> None:
    pg_receipts[1]["reupgrade_base"] = pg_receipts[1]["fresh_upgrade"]
    assert not _read_pg(pg_receipts)["valid"]


@pytest.mark.parametrize(
    ("step", "direction", "transitions"),
    [
        (
            "fresh_upgrade",
            "upgrade",
            [("not_base", "synthetic_previous"), ("synthetic_previous", "synthetic_head")],
        ),
        ("fresh_upgrade", "upgrade", [("", "unrelated"), ("synthetic_previous", "synthetic_head")]),
        (
            "fresh_upgrade",
            "upgrade",
            [
                ("", "synthetic_previous"),
                ("synthetic_previous", ""),
                ("", "synthetic_previous"),
                ("synthetic_previous", "synthetic_head"),
            ],
        ),
        ("reupgrade_base", "upgrade", [("", "synthetic_head")]),
        ("downgrade_base", "downgrade", [("synthetic_head", "synthetic_previous")]),
        ("downgrade_one", "downgrade", [("synthetic_head", "")]),
    ],
)
def test_incomplete_or_inconsistent_roundtrips_rejected(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]],
    step: MigrationStep,
    direction: str,
    transitions: list[tuple[str, str]],
) -> None:
    pg_receipts[1][step].path.write_text(_log(direction, transitions), encoding="utf-8")
    assert not _read_pg(pg_receipts)["valid"]


@pytest.mark.parametrize("context", ["SQLiteImpl", "MySQLImpl", "OracleImpl"])
def test_mixed_database_logs_rejected(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]], context: str
) -> None:
    path = pg_receipts[1]["fresh_upgrade"].path
    path.write_text(
        path.read_text(encoding="utf-8") + f"\nContext impl {context}.\n", encoding="utf-8"
    )
    assert not _read_pg(pg_receipts)["valid"]


@pytest.mark.parametrize(
    ("ids", "head", "previous"),
    [
        (frozenset(), "synthetic_head", "synthetic_previous"),
        (frozenset({TEST_ID}), "", "synthetic_previous"),
        (frozenset({TEST_ID}), "synthetic_head", "synthetic_head"),
    ],
)
def test_explicit_scope_required(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]],
    ids: frozenset[str],
    head: str,
    previous: str,
) -> None:
    junit, migrations = pg_receipts
    result = read_postgres_receipts(
        junit,
        migrations=migrations,
        expected_test_ids=ids,
        expected_head=head,
        expected_previous=previous,
    )
    assert not result["valid"]


def test_linked_receipts_rejected(
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.is_symlink
    path = pg_receipts[0].path
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == path or original(self))
    assert not _read_pg(pg_receipts)["valid"]


@pytest.fixture
def gate_context(
    sealed_bundle: tuple[Path, Path, str],
    pg_receipts: tuple[CommandReceipt, dict[MigrationStep, CommandReceipt]],
) -> tuple[Path, Path, Path]:
    repo, bundle, digest = sealed_bundle
    junit, migrations = pg_receipts
    inputs = verification_run.snapshot_inputs(repo)["sha256"]
    manifest = repo / "synthetic_postgres_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "repository_input_sha256": inputs,
                "inputs_unchanged": True,
                "input_sha256_before": inputs,
                "input_sha256_after": inputs,
                "junit": {
                    "path": str(junit.path),
                    "returncode": 0,
                    "sha256": sha256(junit.path.read_bytes()).hexdigest(),
                },
                "migrations": {
                    step: {
                        "path": str(receipt.path),
                        "returncode": 0,
                        "sha256": sha256(receipt.path.read_bytes()).hexdigest(),
                    }
                    for step, receipt in migrations.items()
                },
                "expected_test_ids": [TEST_ID],
                "expected_head": "synthetic_head",
                "expected_previous": "synthetic_previous",
            }
        ),
        encoding="utf-8",
    )
    context = repo / "tasks/verification_receipts.yaml"
    context.parent.mkdir()
    context.write_text(
        yaml.safe_dump(
            {
                "offline_bundle": {"path": str(bundle), "sha256": digest},
                "postgres": {
                    "manifest_path": manifest.name,
                    "sha256": sha256(manifest.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    return context, repo, manifest


def _read_context(context: Path, repo: Path) -> dict[str, ReceiptResult]:
    return read_gate_receipts(
        context, repo, frozenset({TEST_ID}), "synthetic_head", "synthetic_previous"
    )


def _seal_synthetic_manifest(context: Path, manifest: Path) -> None:
    value = yaml.safe_load(context.read_text(encoding="utf-8"))
    value["postgres"]["sha256"] = sha256(manifest.read_bytes()).hexdigest()
    context.write_text(yaml.safe_dump(value), encoding="utf-8")


def test_gate_context_binds_postgres_to_current_inputs(
    gate_context: tuple[Path, Path, Path],
) -> None:
    context, repo, manifest = gate_context
    result = _read_context(context.relative_to(repo), repo)
    assert set(result) == {"coverage", "postgres"}
    for receipt in result.values():
        assert receipt["valid"] and receipt["current_code_verified"]
        assert receipt["code_fingerprint_status"] == "current"
        assert receipt["full_chain_eval"] is False
        assert receipt["metrics"]["tests"] == 1
        assert receipt["provenance"]["context_sha256"] == sha256(context.read_bytes()).hexdigest()
    pg = result["postgres"]
    assert pg["provenance"]["expected_manifest_sha256"] == sha256(manifest.read_bytes()).hexdigest()
    assert pg["provenance"]["execution_authenticated"] is False
    assert "code_fingerprint_not_recorded" not in pg["warnings"]


def test_gate_context_stale_fingerprint_is_not_current(
    gate_context: tuple[Path, Path, Path],
) -> None:
    context, repo, _ = gate_context
    (repo / "src/cloud_expert/synthetic.py").write_text("value = 2\n", encoding="utf-8")
    for receipt in _read_context(context, repo).values():
        assert receipt["valid"] and not receipt["current_code_verified"]
        assert receipt["code_fingerprint_status"] == "stale"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[broken",
        "[]",
        "{}",
        "offline_bundle: null\npostgres: null",
        "offline_bundle: {}\noffline_bundle: {}\npostgres: {}",
    ],
)
def test_malformed_context_fails_closed(gate_context: tuple[Path, Path, Path], text: str) -> None:
    context, repo, _ = gate_context
    context.write_text(text, encoding="utf-8")
    assert all(not result["valid"] for result in _read_context(context, repo).values())


@pytest.mark.parametrize("missing", ["context", "manifest"])
def test_missing_context_or_manifest_has_no_fallback(
    gate_context: tuple[Path, Path, Path], missing: str
) -> None:
    context, repo, manifest = gate_context
    (context if missing == "context" else manifest).unlink()
    assert all(not result["valid"] for result in _read_context(context, repo).values())


def test_changed_manifest_rejected_by_independent_sha(
    gate_context: tuple[Path, Path, Path],
) -> None:
    context, repo, manifest = gate_context
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    assert all(not result["valid"] for result in _read_context(context, repo).values())


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("expected_test_ids", [TEST_ID, TEST_ID]),
        ("expected_test_ids", ["invented"]),
        ("expected_head", "wrong_head"),
        ("expected_previous", "wrong_previous"),
        ("repository_input_sha256", "not-a-digest"),
        ("migrations", {}),
        ("junit", {"path": "missing.xml", "returncode": 0}),
    ],
)
def test_manifest_cannot_choose_gate_scope(
    gate_context: tuple[Path, Path, Path], key: str, value: Any
) -> None:
    context, repo, manifest = gate_context
    data = json.loads(manifest.read_bytes())
    data[key] = value
    manifest.write_text(json.dumps(data), encoding="utf-8")
    _seal_synthetic_manifest(context, manifest)
    assert not _read_context(context, repo)["postgres"]["valid"]


@pytest.mark.parametrize("text", ["[]", "null", "not JSON", '{"junit": {}, "junit": {}}'])
def test_malformed_manifest_rejected(gate_context: tuple[Path, Path, Path], text: str) -> None:
    context, repo, manifest = gate_context
    manifest.write_text(text, encoding="utf-8")
    _seal_synthetic_manifest(context, manifest)
    assert not _read_context(context, repo)["postgres"]["valid"]


@pytest.mark.parametrize("target", ["context", "manifest"])
def test_pointers_changed_during_validation_fail_closed(
    gate_context: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    context, repo, manifest = gate_context
    snapshot = verification_run.snapshot_inputs

    def mutate(root: Path) -> dict[str, Any]:
        path = context if target == "context" else manifest
        path.write_bytes(path.read_bytes() + b"\n")
        return snapshot(root)

    monkeypatch.setattr(verification_run, "snapshot_inputs", mutate)
    result = _read_context(context, repo)
    assert all(
        not receipt["valid"] and not receipt["current_code_verified"] for receipt in result.values()
    )


@pytest.mark.parametrize("name", ["junit", *MIGRATION_STEPS])
@pytest.mark.parametrize("change", ["artifact_bytes", "missing_hash", "wrong_hash"])
def test_manifest_binds_every_artifact(
    gate_context: tuple[Path, Path, Path],
    name: str,
    change: str,
) -> None:
    context, repo, manifest = gate_context
    value = json.loads(manifest.read_bytes())
    entry = value["junit"] if name == "junit" else value["migrations"][name]
    if change == "artifact_bytes":
        artifact = Path(entry["path"])
        artifact.write_bytes(artifact.read_bytes() + b"\n")
    else:
        if change == "missing_hash":
            del entry["sha256"]
        else:
            entry["sha256"] = "0" * 64
        manifest.write_text(json.dumps(value), encoding="utf-8")
        _seal_synthetic_manifest(context, manifest)
    result = _read_context(context, repo)["postgres"]
    assert not result["valid"] and not result["current_code_verified"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("inputs_unchanged", False),
        ("inputs_unchanged", 1),
        ("inputs_unchanged", "true"),
        ("input_sha256_before", "0" * 64),
        ("input_sha256_after", "0" * 64),
    ],
)
def test_postgres_execution_inputs_must_be_unchanged(
    gate_context: tuple[Path, Path, Path],
    key: str,
    value: Any,
) -> None:
    context, repo, manifest = gate_context
    data = json.loads(manifest.read_bytes())
    data[key] = value
    manifest.write_text(json.dumps(data), encoding="utf-8")
    _seal_synthetic_manifest(context, manifest)
    assert not _read_context(context, repo)["postgres"]["valid"]


def test_shared_postgres_scope_is_fixed_to_fourteen_named_tests() -> None:
    assert isinstance(EXPECTED_POSTGRES_TEST_IDS, frozenset)
    assert len(EXPECTED_POSTGRES_TEST_IDS) == 14
    modules = [identity.split("::")[0] for identity in EXPECTED_POSTGRES_TEST_IDS]
    assert {module: modules.count(module) for module in set(modules)} == {
        "tests.integration.test_postgres_r011": 6,
        "tests.integration.test_postgres_market": 1,
        "tests.integration.test_postgres_model_review": 1,
        "tests.integration.test_postgres_price_lifecycle": 2,
        "tests.integration.test_postgres_price_quarantine": 4,
    }
    assert EXPECTED_HEAD == "0014_week14_review_workflow"
    assert EXPECTED_PREVIOUS == "0013_week12_market_context"
