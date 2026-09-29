"""Synthetic runner receipts only. Never launch the repository's full verification suite."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from cloud_expert.evals import verification_run as verification

JUNIT = b'<testsuites><testsuite tests="2" errors="0" failures="0" skipped="0"><testcase classname="synthetic" name="one"/><testcase classname="synthetic" name="two"/></testsuite></testsuites>'


def _coverage(percent: int = 90) -> dict[str, Any]:
    summary = {
        "covered_lines": percent,
        "num_statements": 100,
        "missing_lines": 100 - percent,
        "covered_branches": 0,
        "num_branches": 0,
        "missing_branches": 0,
        "percent_covered": percent,
    }
    return {
        "meta": {"branch_coverage": True},
        "files": {"src/cloud_expert/example.py": {"summary": summary}},
        "totals": dict(summary),
    }


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "synthetic_repository"
    for relative in verification.INPUT_DIRS:
        (root / relative).mkdir(parents=True)
    contents = {
        "src/cloud_expert/example.py": b"value = 'synthetic'\n",
        "tests/unit/test_example.py": b"def test_synthetic():\n    assert True\n",
        "tests/migrations/test_example.py": b"def test_synthetic_migration():\n    assert True\n",
        "tests/fixtures/payload.bin": b"synthetic binary fixture\x00\xff",
        "config/policy.yaml": b"synthetic: true\n",
        "alembic/versions/0001.py": b"revision = 'synthetic'\n",
        "scripts/example.py": b"print('synthetic')\n",
        "data/source_registry/source.yaml": b"url: https://example.invalid/synthetic\n",
        "pyproject.toml": b"[project]\nname = 'synthetic'\n",
        "alembic.ini": b"[alembic]\nscript_location = alembic\n",
        "docs/example.md": b"Synthetic documentation input\n",
    }
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    # These are deliberately excluded from the executable workspace and input manifests.
    (root / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")
    (root / "business.sqlite").write_bytes(b"not a real database")
    (root / "data/raw").mkdir()
    (root / "data/raw/private.bin").write_bytes(b"do-not-copy")
    return root


@dataclass
class Runner:
    junit: bytes | None = JUNIT
    coverage: dict[str, Any] | None = field(default_factory=_coverage)
    exit_codes: dict[str, int] = field(default_factory=dict)
    calls: list[tuple[list[str], dict[str, Any]]] = field(default_factory=list)
    callback: Callable[[str, Path], None] | None = None
    failure: Exception | None = None

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        names = ("pytest", "ruff_check", "ruff_format", "mypy")
        name = names[len(self.calls)]
        self.calls.append((argv, kwargs))
        output = Path(kwargs["cwd"]).parent
        if self.failure is not None:
            raise self.failure
        if name == "pytest":
            if self.junit is not None:
                (output / "junit.xml").write_bytes(self.junit)
            if self.coverage is not None:
                (output / "coverage.json").write_text(json.dumps(self.coverage), encoding="utf-8")
        if self.callback is not None:
            self.callback(name, output)
        return subprocess.CompletedProcess(
            argv,
            self.exit_codes.get(name, 0),
            f"synthetic {name} stdout".encode(),
            b"synthetic stderr",
        )


def _run(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: Runner | None = None
) -> tuple[Path, dict[str, Any], Runner]:
    runner = runner or Runner()
    monkeypatch.setattr(subprocess, "run", runner)
    output = tmp_path / "new_exclusive_bundle"
    result = verification.run_verification(repository, output, execute=True)
    return output, result, runner


def _verify(output: Path, result: dict[str, Any]) -> dict[str, Any]:
    return verification.validate_verification_bundle(
        output, expected_manifest_sha256=result["manifest_sha256"]
    )


def test_default_plan_never_executes_or_creates_output(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = Runner()
    monkeypatch.setattr(subprocess, "run", runner)
    output = tmp_path / "not_created"
    result = verification.run_verification(repository, output)
    assert result["status"] == "planned" and result["passed"] is False
    assert not output.exists() and runner.calls == []
    assert [command["name"] for command in result["commands"]] == [
        "pytest",
        "ruff_check",
        "ruff_format",
        "mypy",
    ]
    assert all("--fix" not in command["argv"] for command in result["commands"])


def test_actual_runner_path_seals_fixed_commands_and_isolated_artifacts(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUAWEI_SECRET_KEY", "never-transfer-this-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret:password@business/db")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--skip-everything")
    output, result, runner = _run(repository, tmp_path, monkeypatch)
    assert result["passed"] is True and result["tests_valid"] is True
    assert result["inputs_unchanged"] is True and result["tests"] == 2
    assert result["coverage_percent"] == 90
    assert all(
        result[key] is False
        for key in (
            "full_chain_eval",
            "model_judge",
            "postgres_executed",
            "business_database_writeback",
            "gate_updated",
            "customer_eligible",
        )
    )
    assert _verify(output, result) == result
    for argv, options in runner.calls:
        assert options["shell"] is False and options["stdin"] == subprocess.DEVNULL
        assert options["cwd"] == output / "workspace"
        assert argv[:3] == [str(Path(sys.executable).resolve()), "-B", "-m"]
        assert "HUAWEI_SECRET_KEY" not in options["env"]
        assert "PYTEST_ADDOPTS" not in options["env"]
        assert options["env"]["DATABASE_URL"] == "sqlite:///:memory:"
    pytest_argv, pytest_options = runner.calls[0]
    assert "tests/unit" in pytest_argv and "tests/migrations" in pytest_argv
    assert "not network and not postgres" in pytest_argv
    assert f"--basetemp={output / 'pytest_basetemp'}" in pytest_argv
    assert pytest_options["env"]["CLOUD_EXPERT_VERIFICATION_ROOT"] == str(output)
    assert (output / "workspace/tests/fixtures/payload.bin").read_bytes().endswith(b"\x00\xff")
    assert not (output / "workspace/.env").exists()
    assert not (output / "workspace/business.sqlite").exists()
    assert not (output / "workspace/data/raw").exists()
    assert (repository / "business.sqlite").read_bytes() == b"not a real database"
    assert (output / "commands/pytest.stdout.txt").read_bytes() == b"synthetic pytest stdout"
    for path in output.glob("**/*.json"):
        assert b"never-transfer-this-secret" not in path.read_bytes()
        assert b"postgresql://secret" not in path.read_bytes()


@pytest.mark.parametrize(
    "relative",
    [
        "src/cloud_expert/example.py",
        "tests/unit/test_example.py",
        "tests/fixtures/payload.bin",
        "config/policy.yaml",
        "alembic/versions/0001.py",
        "data/source_registry/source.yaml",
        "pyproject.toml",
        "alembic.ini",
        "scripts/example.py",
        "docs/example.md",
    ],
)
def test_concurrent_edits_in_every_input_scope_invalidate_success(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    def edit(name: str, output: Path) -> None:
        if name == "pytest":
            path = repository / relative
            path.write_bytes(path.read_bytes() + b"\nchanged during verification")

    _, result, _ = _run(repository, tmp_path, monkeypatch, Runner(callback=edit))
    assert result["passed"] is False and result["tests_valid"] is False
    assert result["inputs_unchanged"] is False
    assert "inputs_changed_during_verification" in result["errors"]


@pytest.mark.parametrize("operation", ["add", "delete", "restore", "staged"])
def test_input_inventory_and_intermediate_changes_cannot_be_hidden(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path = repository / "config/policy.yaml"
    original = path.read_bytes()

    def change(name: str, output: Path) -> None:
        if name == "pytest":
            if operation == "add":
                (repository / "src/new.py").write_text("changed = True\n", encoding="utf-8")
            elif operation == "delete":
                path.unlink()
            elif operation == "staged":
                (output / "workspace/config/policy.yaml").write_bytes(b"mutated staged input")
            else:
                path.write_bytes(b"temporary change")
        elif name == "ruff_check" and operation == "restore":
            path.write_bytes(original)

    output, result, _ = _run(repository, tmp_path, monkeypatch, Runner(callback=change))
    assert not result["passed"] and not result["tests_valid"]
    if operation == "restore":
        assert json.loads((output / "inputs.before.json").read_bytes()) == json.loads(
            (output / "inputs.after.json").read_bytes()
        )


@pytest.mark.parametrize("command", ["pytest", "ruff_check", "ruff_format", "mypy"])
def test_any_failed_allowlisted_command_blocks_success(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    _, result, runner = _run(repository, tmp_path, monkeypatch, Runner(exit_codes={command: 1}))
    assert len(runner.calls) == 4
    assert not result["passed"] and "command_failed" in result["errors"]


@pytest.mark.parametrize(
    "junit",
    [
        None,
        b"",
        b"<testsuites/>",
        b"not XML",
        JUNIT.replace(b'failures="0"', b'failures="1"'),
        JUNIT.replace(b'errors="0"', b'errors="1"'),
        JUNIT.replace(b'skipped="0"', b'skipped="1"'),
        JUNIT.replace(b'tests="2"', b'tests="0"'),
        JUNIT.replace(b'name="one"/>', b'name="one"><failure/></testcase>'),
    ],
)
def test_missing_empty_inconsistent_or_failed_junit_cannot_pass(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, junit: bytes | None
) -> None:
    _, result, _ = _run(repository, tmp_path, monkeypatch, Runner(junit=junit))
    assert result["passed"] is False and result["tests_valid"] is False


@pytest.mark.parametrize("percent,passed", [(84, False), (85, True), (100, True)])
def test_coverage_threshold_is_measured_not_a_passed_flag(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, percent: int, passed: bool
) -> None:
    _, result, _ = _run(repository, tmp_path, monkeypatch, Runner(coverage=_coverage(percent)))
    assert result["passed"] is passed


@pytest.mark.parametrize(
    "defect", ["missing", "empty", "no_branches", "lying_percent", "lying_counts", "nonfinite"]
)
def test_missing_or_fabricated_coverage_is_rejected(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    coverage = _coverage()
    if defect == "empty":
        coverage["files"] = {}
    elif defect == "no_branches":
        coverage["meta"]["branch_coverage"] = False
    elif defect == "lying_percent":
        coverage["totals"]["percent_covered"] = 100
    elif defect == "lying_counts":
        coverage["totals"]["num_statements"] = 0
    elif defect == "nonfinite":
        coverage["totals"]["percent_covered"] = float("nan")
    _, result, _ = _run(
        repository,
        tmp_path,
        monkeypatch,
        Runner(coverage=None if defect == "missing" else coverage),
    )
    assert not result["passed"]


@pytest.mark.parametrize("covered_branches,passed", [(50, False), (80, True)])
def test_coverage_threshold_includes_branch_denominator(
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    covered_branches: int,
    passed: bool,
) -> None:
    coverage = _coverage(90)
    for summary in (
        coverage["totals"],
        coverage["files"]["src/cloud_expert/example.py"]["summary"],
    ):
        summary.update(
            num_branches=100,
            covered_branches=covered_branches,
            missing_branches=100 - covered_branches,
            percent_covered=(90 + covered_branches) / 2,
        )
    _, result, _ = _run(repository, tmp_path, monkeypatch, Runner(coverage=coverage))
    assert result["passed"] is passed
    assert result["coverage_percent"] == (90 + covered_branches) / 2


@pytest.mark.parametrize(
    "relative",
    [
        "manifest.json",
        "plan.json",
        "junit.xml",
        "coverage.json",
        "inputs.before.json",
        "inputs.after.json",
        "inputs.pytest.before.json",
        "inputs.mypy.after.json",
        "workspace.before.json",
        "workspace.after.json",
        "commands/pytest.receipt.json",
        "commands/ruff_check.stdout.txt",
        "commands/mypy.stderr.txt",
        "runtime/guard/sitecustomize.py",
        "workspace/src/cloud_expert/example.py",
    ],
)
def test_every_receipt_artifact_and_staged_input_is_hash_checked(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    output, result, _ = _run(repository, tmp_path, monkeypatch)
    path = output / relative
    path.write_bytes(path.read_bytes() + b"tampered")
    assert _verify(output, result)["passed"] is False


@pytest.mark.parametrize(
    "defect",
    ["missing_receipts", "outside_path", "changed_argv", "shell", "timestamps", "passed_flag"],
)
def test_caller_passed_flag_and_forged_receipts_do_not_determine_verdict(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    output, result, _ = _run(
        repository,
        tmp_path,
        monkeypatch,
        Runner(exit_codes={"mypy": 1} if defect == "passed_flag" else {}),
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["passed"] = True
    if defect == "missing_receipts":
        manifest["commands"] = []
    elif defect == "outside_path":
        manifest["inputs_after"]["path"] = "../outside.json"
    elif defect != "passed_flag":
        path = output / "commands/pytest.receipt.json"
        receipt = json.loads(path.read_bytes())
        if defect == "changed_argv":
            receipt["argv"] = ["unapproved-command"]
        elif defect == "shell":
            receipt["shell"] = True
        else:
            receipt["finished_at"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        manifest["commands"][0] = verification._ref(output, path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not _verify(output, result)["passed"]
    # Even a newly supplied hash does not bypass structural/command/result validation.
    fresh_hash = sha256(manifest_path.read_bytes()).hexdigest()
    assert not verification.validate_verification_bundle(
        output, expected_manifest_sha256=fresh_hash
    )["passed"]


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("synthetic missing interpreter"),
        subprocess.TimeoutExpired("synthetic", 1, output=b"partial", stderr=b"timed out"),
    ],
)
def test_launch_failure_or_timeout_keeps_failure_receipts(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    output, result, runner = _run(repository, tmp_path, monkeypatch, Runner(failure=failure))
    assert not result["passed"] and len(runner.calls) == 4
    assert (output / "inputs.after.json").is_file()
    assert json.loads((output / "commands/pytest.receipt.json").read_bytes())["execution_error"]


def test_output_reuse_input_overlap_and_missing_anchor_are_rejected(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, result, runner = _run(repository, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="must_be_new"):
        verification.run_verification(repository, output, execute=True)
    assert len(runner.calls) == 4 and _verify(output, result)["passed"]
    with pytest.raises(ValueError, match="overlaps_inputs"):
        verification.plan_verification(repository, repository / "tests/new_output")
    assert not verification.validate_verification_bundle(output, expected_manifest_sha256="")[
        "passed"
    ]


def test_missing_required_input_creates_no_success_or_child_process(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repository / "pyproject.toml").unlink()
    _, result, runner = _run(repository, tmp_path, monkeypatch)
    assert not result["passed"] and runner.calls == []


def test_linked_inputs_are_rejected_without_following_them(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path.name == "example.py" or original(path)
    )
    with pytest.raises(ValueError, match="linked_path"):
        verification.snapshot_inputs(repository)


@pytest.mark.parametrize("defect", ["root_failures", "root_count", "outside_case_failure"])
def test_junit_outer_summary_cannot_hide_failures(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    replacements = {
        "root_failures": b'<testsuites failures="1">',
        "root_count": b'<testsuites tests="0">',
        "outside_case_failure": b"<testsuites><failure/>",
    }
    junit = JUNIT.replace(b"<testsuites>", replacements[defect])
    _, result, _ = _run(repository, tmp_path, monkeypatch, Runner(junit=junit))
    assert not result["passed"]


@pytest.mark.parametrize("defect", ["missing_file", "outside_source", "duplicate_alias"])
def test_coverage_must_cover_the_sealed_source_inventory(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    coverage = _coverage()
    if defect == "missing_file":
        (repository / "src/cloud_expert/unreported.py").write_text("x = 1\n", encoding="utf-8")
    elif defect == "outside_source":
        coverage["files"]["../../outside.py"] = coverage["files"].pop("src/cloud_expert/example.py")
    else:
        coverage["files"]["src/cloud_expert/../cloud_expert/example.py"] = coverage["files"][
            "src/cloud_expert/example.py"
        ]
    _, result, _ = _run(repository, tmp_path, monkeypatch, Runner(coverage=coverage))
    assert not result["passed"]


def _guarded_environment(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    output = tmp_path / "guard_probe"
    output.mkdir()
    if os.environ.get("CLOUD_EXPERT_VERIFICATION_ROOT"):
        # Nested inside the real offline suite, retain its already enforced guard.
        environment = dict(os.environ)
    else:
        for relative in ("runtime/home", "runtime/tmp", "runtime/raw", "runtime/guard"):
            (output / relative).mkdir(parents=True)
        (output / "runtime/guard/sitecustomize.py").write_text(
            verification.GUARD_BOOTSTRAP, encoding="utf-8"
        )
        repository_root = Path(__file__).resolve().parents[2]
        environment = verification._environment(repository_root, output, guarded=True)
    return output, environment


def test_bootstrap_installs_guard_in_a_small_real_python_child(tmp_path: Path) -> None:
    output, environment = _guarded_environment(tmp_path)
    probe = """
import json, os, sqlite3, subprocess, sys
from pathlib import Path
outside_path = Path(os.environ['CLOUD_EXPERT_VERIFICATION_ROOT']).parent / 'never-written.sqlite'
outside = str(outside_path)
denied = []
for event, args in [('socket.connect', (None, ('127.0.0.1', 5432))),
                    ('sqlite3.connect', (outside,)),
                    ('sqlite3.connect', (outside_path.as_uri() + '?mode=ro',)),
                    ('open', (outside, 'wb', os.O_CREAT))]:
    try:
        sys.audit(event, *args)
    except (PermissionError, ValueError):
        denied.append(event)
Path(sys.argv[1]).write_text('synthetic allowed output')
database = Path(sys.argv[1]).parent / 'synthetic space # %.sqlite'
with sqlite3.connect(database.as_uri() + '?mode=rwc', uri=True) as connection:
    connection.execute('CREATE TABLE synthetic (id INTEGER)')
before = database.read_bytes()
with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
    assert connection.execute('SELECT COUNT(*) FROM synthetic').fetchone() == (0,)
    try:
        connection.execute('CREATE TABLE forbidden (id INTEGER)')
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError('read-only URI lost its protection')
assert database.read_bytes() == before
# The grandchild must load the same bootstrap too, including on Windows.
grandchild = subprocess.run(
    [sys.executable, '-B', '-c', 'import sys; sys.audit("socket.connect", None, ("127.0.0.1", 5432))'],
    capture_output=True, text=True, check=False, shell=False,
)
assert grandchild.returncode != 0 and 'offline_network_or_external_execution_denied' in grandchild.stderr
print(json.dumps(denied))
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(output / "allowed.txt")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        "socket.connect",
        "sqlite3.connect",
        "sqlite3.connect",
        "open",
    ]
    assert (output / "allowed.txt").read_text() == "synthetic allowed output"


@pytest.fixture
def guard_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Callable[[str, tuple[Any, ...]], None]]:
    root = tmp_path / "isolated_output"
    root.mkdir()
    monkeypatch.setenv("CLOUD_EXPERT_VERIFICATION_ROOT", str(root))
    monkeypatch.setenv("PYTHONPATH", "synthetic-guard-path")
    hooks: list[Callable[[str, tuple[Any, ...]], None]] = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    verification.install_offline_guard()
    return root, hooks[0]


def test_file_uri_resolves_to_the_same_bounded_native_path(
    guard_audit: tuple[Path, Callable[[str, tuple[Any, ...]], None]],
) -> None:
    root, audit = guard_audit
    database = root / "synthetic space # %.sqlite"
    for value in (str(database), database.as_uri()):
        assert Path(verification._sqlite_filename(value)).resolve() == database.resolve()
        audit("sqlite3.connect", (value,))
    audit("sqlite3.connect", (database.as_uri() + "?mode=ro&immutable=1",))
    outside = root.parent / "not-a-business-database.sqlite"
    for value in (str(outside), outside.as_uri(), outside.as_uri() + "?mode=ro"):
        with pytest.raises(ValueError, match="offline_write_outside_output"):
            audit("sqlite3.connect", (value,))
    traversal = root.as_uri() + "/%2e%2e/not-a-business-database.sqlite?mode=rw"
    with pytest.raises(ValueError, match="offline_write_outside_output"):
        audit("sqlite3.connect", (traversal,))
    assert not outside.exists()


@pytest.mark.parametrize(
    "value",
    [
        "file://host/share/database.sqlite",
        "file://localhost/database.sqlite",
        "file:////host/share/database.sqlite",
        "file:%2f%2fhost/share/database.sqlite",
        "file:%5c%5chost/share/database.sqlite",
        "file:/synthetic%00.sqlite",
        "file:/synthetic\n.sqlite",
    ],
)
def test_file_uri_rejects_authorities_unc_and_control_characters(value: str) -> None:
    with pytest.raises(ValueError, match="offline_database_"):
        verification._sqlite_filename(value)


@pytest.mark.parametrize("executable", [None, sys.executable])
def test_python_child_audit_accepts_native_argv_and_windows_command_line(
    guard_audit: tuple[Path, Callable[[str, tuple[Any, ...]], None]], executable: str | None
) -> None:
    _, audit = guard_audit
    arguments = [sys.executable, "-B", "-c", 'print("synthetic quoted value")', "a path\\", "-I"]
    forms: list[Any] = [arguments, tuple(arguments)]
    if os.name == "nt":
        forms.append(subprocess.list2cmdline(arguments))
    for argv in forms:
        audit("subprocess.Popen", (executable, argv, None, None))


@pytest.mark.parametrize("flags", [["-I"], ["-E"], ["-S"], ["-BIS"], ["-W", "ignore", "-S"]])
def test_guard_disabling_python_options_remain_denied_in_both_argv_forms(
    guard_audit: tuple[Path, Callable[[str, tuple[Any, ...]], None]], flags: list[str]
) -> None:
    _, audit = guard_audit
    arguments = [sys.executable, *flags, "-c", "pass"]
    forms: list[Any] = [arguments]
    if os.name == "nt":
        forms.append(subprocess.list2cmdline(arguments))
    for argv in forms:
        with pytest.raises(ValueError, match="offline_child_guard_disabled"):
            audit("subprocess.Popen", (None, argv, None, None))


@pytest.mark.parametrize("changed_key", ["CLOUD_EXPERT_VERIFICATION_ROOT", "PYTHONPATH"])
@pytest.mark.parametrize("change", ["remove", "replace", "prepend"])
def test_child_cannot_lose_or_replace_the_inherited_guard(
    guard_audit: tuple[Path, Callable[[str, tuple[Any, ...]], None]], changed_key: str, change: str
) -> None:
    _, audit = guard_audit
    environment = dict(os.environ)
    if change == "remove":
        environment.pop(changed_key)
    else:
        environment[changed_key] = "foreign" + (
            os.pathsep + environment[changed_key] if change == "prepend" else ""
        )
    with pytest.raises(ValueError, match="offline_child_guard_missing"):
        audit("subprocess.Popen", (None, [sys.executable, "-c", "pass"], None, environment))


@pytest.mark.parametrize(
    "key,alias",
    [
        ("PYTHONPATH", "pythonpath"),
        ("PYTHONPATH", "PythonPath"),
        ("CLOUD_EXPERT_VERIFICATION_ROOT", "cloud_expert_verification_root"),
        ("CLOUD_EXPERT_VERIFICATION_ROOT", "Cloud_Expert_Verification_Root"),
        ("PATH", "Path"),
        ("SYNTHETIC_OTHER", "synthetic_other"),
    ],
)
@pytest.mark.parametrize("same_value", [False, True])
def test_windows_environment_duplicates_are_rejected_before_guard_values(
    guard_audit: tuple[Path, Callable[[str, tuple[Any, ...]], None]],
    key: str,
    alias: str,
    same_value: bool,
) -> None:
    _, audit = guard_audit
    environment = dict(os.environ)
    environment.setdefault(key, "synthetic")
    environment[alias] = environment[key] if same_value else ""
    if os.name == "nt":
        with pytest.raises(ValueError, match="offline_environment_duplicate_key"):
            audit("subprocess.Popen", (None, [sys.executable, "-c", "pass"], None, environment))
    else:
        # POSIX keys are case-sensitive, so these aliases cannot replace PYTHONPATH.
        assert verification._canonical_environment(environment) == environment


def test_runner_emits_unambiguous_windows_environment(tmp_path: Path) -> None:
    environment = verification._environment(tmp_path / "workspace", tmp_path, guarded=True)
    assert len({key.upper() for key in environment}) == len(environment)
    assert environment["PYTHONPATH"]
    assert environment["CLOUD_EXPERT_VERIFICATION_ROOT"] == str(tmp_path)


def test_real_outer_guard_blocks_case_alias_child_environments(tmp_path: Path) -> None:
    output, environment = _guarded_environment(tmp_path)
    probe = """
import json, os, subprocess, sys
# Audit events alone exercise the guard without making any network connection.
child_code = '''import sys
try:
    sys.audit("socket.connect", None, ("127.0.0.1", 9))
except PermissionError:
    print("GUARD_PRESENT")
else:
    print("GUARD_ABSENT")
'''
def child(env):
    return subprocess.run(
        [sys.executable, '-B', '-c', child_code], env=env, shell=False,
        capture_output=True, text=True, check=False, timeout=10,
    )
baseline = dict(os.environ)
control = child(None)
assert control.returncode == 0 and control.stdout.strip() == 'GUARD_PRESENT', control.stderr
aliases = (
    ('PYTHONPATH', 'pythonpath'), ('PYTHONPATH', 'PythonPath'),
    ('CLOUD_EXPERT_VERIFICATION_ROOT', 'cloud_expert_verification_root'),
    ('CLOUD_EXPERT_VERIFICATION_ROOT', 'Cloud_Expert_Verification_Root'),
)
blocked_explicit = blocked_inherited = 0
for key, alias in aliases:
    for alias_first in (False, True):
        candidate = {alias: '', **baseline} if alias_first else {**baseline, alias: ''}
        assert candidate[key] == baseline[key] and candidate[alias] == ''
        try:
            result = child(candidate)
        except ValueError as exc:
            assert os.name == 'nt' and str(exc) == 'offline_environment_duplicate_key', str(exc)
            blocked_explicit += 1
        else:
            assert os.name != 'nt', ('case alias launched a child', alias, result.stdout, result.stderr)
            assert result.returncode == 0 and result.stdout.strip() == 'GUARD_PRESENT'
    try:
        os.environ[alias] = ''
        try:
            result = child(None)
        except ValueError as exc:
            assert os.name == 'nt' and str(exc) == 'offline_child_guard_missing', str(exc)
            blocked_inherited += 1
        else:
            assert os.name != 'nt', ('inherited alias launched a child', alias, result.stdout)
            assert result.returncode == 0 and result.stdout.strip() == 'GUARD_PRESENT'
    finally:
        os.environ.clear()
        os.environ.update(baseline)
control = child(dict(os.environ))
assert control.returncode == 0 and control.stdout.strip() == 'GUARD_PRESENT', control.stderr
print(json.dumps({'explicit': blocked_explicit, 'inherited': blocked_inherited}))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        cwd=output,
        env=environment,
        shell=False,
        capture_output=True,
        text=True,
        check=False,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = (
        {"explicit": 8, "inherited": 4} if os.name == "nt" else {"explicit": 0, "inherited": 0}
    )
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize(
    "executable,argv",
    [
        (None, ["curl", "https://example.invalid"]),
        ("foreign-python", [sys.executable, "-c", "pass"]),
        (sys.executable, ["foreign-python", "-c", "pass"]),
        (None, []),
        (None, [None]),
        (42, [sys.executable]),
        (None, [sys.executable, "-c", "pass\x00-S"]),
    ],
)
def test_invalid_or_foreign_child_executables_fail_closed(
    guard_audit: tuple[Path, Callable[[str, tuple[Any, ...]], None]], executable: Any, argv: Any
) -> None:
    _, audit = guard_audit
    with pytest.raises(ValueError, match="offline_"):
        audit("subprocess.Popen", (executable, argv, None, None))


def test_offline_guard_rejects_network_external_writes_databases_and_unguarded_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "isolated_output"
    root.mkdir()
    monkeypatch.setenv("CLOUD_EXPERT_VERIFICATION_ROOT", str(root))
    monkeypatch.setenv("PYTHONPATH", "synthetic-guard-path")
    hooks: list[Callable[[str, tuple[Any, ...]], None]] = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    verification.install_offline_guard()
    audit = hooks[0]
    for event, args in (
        ("socket.connect", (None, ("127.0.0.1", 5432))),
        ("socket.getaddrinfo", ("example.invalid", 443)),
        ("open", (str(tmp_path / "business.sqlite"), "wb", os.O_CREAT)),
        ("sqlite3.connect", (str(tmp_path / "business.sqlite"),)),
        ("sqlite3.connect", ("file://host/database",)),
        ("os.mkdir", (str(tmp_path / "outside"),)),
        ("os.rename", (str(root / "a"), str(tmp_path / "outside"))),
        ("subprocess.Popen", ("curl", ["curl", "https://example.invalid"], None, None)),
        ("subprocess.Popen", (sys.executable, [sys.executable, "-I", "-c", "pass"], None, None)),
        ("subprocess.Popen", (sys.executable, [sys.executable, "-c", "pass"], None, {})),
    ):
        with pytest.raises((ValueError, PermissionError)):
            audit(event, args)
    audit("open", (str(root / "synthetic.sqlite"), "wb", os.O_CREAT))
    audit("sqlite3.connect", (":memory:",))
    audit("sqlite3.connect", (f"file:{(root / 'test.sqlite').as_posix()}?mode=ro",))
    audit("subprocess.Popen", (sys.executable, [sys.executable, "-B", "-c", "pass"], None, None))


def test_cli_plan_is_default_and_execute_requires_explicit_flag(
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/run_verification_bundle.py"
    monkeypatch.syspath_prepend(str(script.parent))
    spec = importlib.util.spec_from_file_location("synthetic_verification_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", repository)
    output = tmp_path / "cli_bundle"
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(output)])
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert not output.exists()
    runner = Runner()
    monkeypatch.setattr(subprocess, "run", runner)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(output), "--execute"])
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(script), "--output-dir", str(output), "--verify-sha256", result["manifest_sha256"]],
    )
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["passed"]
    assert len(runner.calls) == 4
