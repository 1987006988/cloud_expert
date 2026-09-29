"""Sealed offline verification receipts, never a release Gate or full-chain Eval.

The external manifest SHA is the trust anchor for later validation. Hashes detect
tampering; they do not authenticate a bundle and SHA supplied together by an
untrusted party. Keep the SHA returned by the actual runner independently.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
from uuid import uuid4
from xml.etree import ElementTree

VERSION = "offline-verification.v1"
INPUT_DIRS = ("src", "tests", "config", "alembic", "scripts", "data/source_registry")
REQUIRED_FILES = ("pyproject.toml", "alembic.ini")
OPTIONAL_FILES = (
    "AGENTS.md",
    "README.md",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
    ".coveragerc",
    "pytest.ini",
    "mypy.ini",
    "ruff.toml",
    ".ruff.toml",
    "setup.cfg",
)
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
MIN_COVERAGE = 85
GUARD_BOOTSTRAP = (
    "from cloud_expert.evals.verification_run import install_offline_guard\n"
    "install_offline_guard()\n"
)
LIMITS = {
    "verification_kind": "offline_verification",
    "full_chain_eval": False,
    "model_judge": False,
    "postgres_executed": False,
    "business_database_writeback": False,
    "gate_updated": False,
    "customer_eligible": False,
}


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        _require(not part.is_symlink() and not part.is_junction(), "linked_path_rejected")


def _inventory(root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in (*INPUT_DIRS, *REQUIRED_FILES):
        _require((root / relative).exists(), f"required_input_missing:{relative}")
    directories = [*INPUT_DIRS, *(["docs"] if (root / "docs").exists() else [])]
    for relative in directories:
        directory = root / relative
        _no_links(directory)
        _require(directory.is_dir(), f"input_not_directory:{relative}")
        for base, names, files in os.walk(directory, followlinks=False):
            for name in names:
                _no_links(Path(base) / name)
            names[:] = sorted(name for name in names if name not in IGNORED_DIRS)
            for name in sorted(files):
                path = Path(base) / name
                _no_links(path)
                if path.suffix not in {".pyc", ".pyo"}:
                    _require(path.is_file(), "input_not_regular_file")
                    paths.append(path)
    for relative in (*REQUIRED_FILES, *OPTIONAL_FILES):
        path = root / relative
        if path.exists():
            _no_links(path)
            _require(path.is_file(), "input_not_regular_file")
            paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def snapshot_inputs(repo_root: Path) -> dict[str, Any]:
    """Hash uncommitted files and fixtures too; never inspect raw/business databases."""
    root = repo_root.absolute()
    _no_links(root)
    root = root.resolve(strict=True)
    paths = _inventory(root)
    files = []
    for path in paths:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        _require(
            (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "input_changed_while_hashing",
        )
        files.append(
            {"path": path.relative_to(root).as_posix(), "sha256": _sha(data), "size": len(data)}
        )
    _require(paths == _inventory(root), "input_inventory_changed_while_hashing")
    return {"files": files, "sha256": _sha(_json_bytes(files))}


def _write(path: Path, data: bytes) -> None:
    _no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def _ref(root: Path, path: Path) -> dict[str, Any]:
    _no_links(path)
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha(data), "size": len(data)}


def _save(root: Path, name: str, value: object) -> dict[str, Any]:
    path = root / name
    _write(path, _json_bytes(value))
    return _ref(root, path)


def _commands(workspace: Path, output: Path, python: str) -> list[dict[str, Any]]:
    prefix = [python, "-B", "-m"]
    return [
        {
            "name": "pytest",
            "timeout_seconds": 7200,
            "argv": prefix
            + [
                "pytest",
                "-c",
                "pyproject.toml",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                "-p",
                "pytest_cov.plugin",
                "-p",
                "pytest_asyncio.plugin",
                "tests/unit",
                "tests/migrations",
                "-m",
                "not network and not postgres",
                "-q",
                f"--basetemp={output / 'pytest_basetemp'}",
                f"--junitxml={output / 'junit.xml'}",
                "--cov=src/cloud_expert",
                "--cov-branch",
                f"--cov-report=json:{output / 'coverage.json'}",
                "--cov-report=term",
                f"--cov-fail-under={MIN_COVERAGE}",
            ],
        },
        {
            "name": "ruff_check",
            "timeout_seconds": 900,
            "argv": prefix
            + [
                "ruff",
                "check",
                "--no-cache",
                "--config",
                "pyproject.toml",
                "src",
                "scripts",
                "tests",
            ],
        },
        {
            "name": "ruff_format",
            "timeout_seconds": 900,
            "argv": prefix
            + [
                "ruff",
                "format",
                "--check",
                "--no-cache",
                "--config",
                "pyproject.toml",
                "src",
                "scripts",
                "tests",
            ],
        },
        {
            "name": "mypy",
            "timeout_seconds": 1800,
            "argv": prefix
            + [
                "mypy",
                "--config-file",
                "pyproject.toml",
                "--cache-dir",
                str(output / "runtime/mypy_cache"),
                "src",
                "scripts",
            ],
        },
    ]


def plan_verification(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root, output = repo_root.absolute(), output_dir.absolute()
    _no_links(root)
    _no_links(output)
    root, output = root.resolve(strict=True), output.resolve()
    _require(not output.exists(), "output_directory_must_be_new")
    _require(not root.is_relative_to(output), "output_cannot_contain_repository")
    for relative in (*INPUT_DIRS, "docs"):
        _require(not output.is_relative_to(root / relative), "output_overlaps_inputs")
    workspace = output / "workspace"
    return {
        "version": VERSION,
        "status": "planned",
        "passed": False,
        **LIMITS,
        "repository": str(root),
        "output_dir": str(output),
        "workspace": str(workspace),
        "python": str(Path(sys.executable).resolve()),
        "input_directories": list(INPUT_DIRS),
        "optional_input_directory": "docs",
        "required_input_files": list(REQUIRED_FILES),
        "optional_input_files": list(OPTIONAL_FILES),
        "commands": _commands(workspace, output, str(Path(sys.executable).resolve())),
    }


def _canonical_environment(environment: Mapping[str, str]) -> dict[str, str]:
    canonical: dict[str, str] = {}
    for key, value in environment.items():
        _require(isinstance(key, str) and isinstance(value, str), "offline_environment_invalid")
        name = key.upper() if os.name == "nt" else key
        _require(name not in canonical, "offline_environment_duplicate_key")
        canonical[name] = value
    return canonical


def _environment(workspace: Path, output: Path, *, guarded: bool) -> dict[str, str]:
    # Deliberately do not inherit credentials, PYTEST_ADDOPTS, proxies, or database settings.
    inherited = _canonical_environment(os.environ)
    environment: dict[str, str] = {
        key: inherited[key] for key in ("SYSTEMROOT", "WINDIR") if key in inherited
    }
    python_dir = str(Path(sys.executable).resolve().parent)
    system = os.environ.get("SYSTEMROOT", "")
    environment.update(
        {
            "PATH": os.pathsep.join([python_dir, str(Path(system) / "System32")])
            if system
            else python_dir,
            "HOME": str(output / "runtime/home"),
            "USERPROFILE": str(output / "runtime/home"),
            "APPDATA": str(output / "runtime/home"),
            "LOCALAPPDATA": str(output / "runtime/home"),
            "TEMP": str(output / "runtime/tmp"),
            "TMP": str(output / "runtime/tmp"),
            "TMPDIR": str(output / "runtime/tmp"),
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "DATABASE_URL": "sqlite:///:memory:",
            "CLOUD_EXPERT_ENV": "test",
            "CLOUD_EXPERT_ENABLE_NETWORK_TESTS": "false",
            "CLOUD_EXPERT_ALLOW_LOCALHOST_FOR_TESTS": "false",
            "CLOUD_EXPERT_RAW_DATA_DIR": str(output / "runtime/raw"),
            "CLOUD_EXPERT_SOURCE_REGISTRY_DIR": str(workspace / "data/source_registry"),
            "COVERAGE_FILE": str(output / "runtime/.coverage"),
            "PYTHONPATH": str(workspace / "src"),
        }
    )
    if guarded:
        environment["CLOUD_EXPERT_VERIFICATION_ROOT"] = str(output)
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(output / "runtime/guard"), str(workspace / "src")]
        )
    return _canonical_environment(environment)


def _checkpoint(output: Path, name: str, root: Path) -> dict[str, Any]:
    try:
        value = snapshot_inputs(root)
    except (OSError, ValueError) as exc:
        value = {"error": type(exc).__name__, "reason": str(exc)}
    return _save(output, name, value)


def run_verification(repo_root: Path, output_dir: Path, *, execute: bool = False) -> dict[str, Any]:
    """Default is a read-only plan. Only explicit execution can issue a sealed receipt."""
    plan = plan_verification(repo_root, output_dir)
    if not execute:
        return plan
    root, output, workspace = (Path(plan[key]) for key in ("repository", "output_dir", "workspace"))
    output.mkdir(parents=True, exist_ok=False)
    started = _now()
    manifest: dict[str, Any] = {
        "version": VERSION,
        "run_id": uuid4().hex,
        **LIMITS,
        "repository": str(root),
        "output_dir": str(output),
        "python": plan["python"],
        "started_at": started,
        "plan": _save(output, "plan.json", plan),
        "commands": [],
        "errors": [],
    }
    manifest["inputs_before"] = _checkpoint(output, "inputs.before.json", root)
    try:
        before = _read_json((output / "inputs.before.json").read_bytes())
        _validate_inputs(before)
        for relative in INPUT_DIRS:
            (workspace / relative).mkdir(parents=True, exist_ok=True)
        for item in before["files"]:
            data = (root / item["path"]).read_bytes()
            _require(_sha(data) == item["sha256"], "input_changed_while_staging")
            _write(workspace / item["path"], data)
        manifest["workspace_before"] = _checkpoint(output, "workspace.before.json", workspace)
        for relative in ("runtime/home", "runtime/tmp", "runtime/raw", "runtime/guard"):
            (output / relative).mkdir(parents=True, exist_ok=False)
        guard = output / "runtime/guard/sitecustomize.py"
        _write(guard, GUARD_BOOTSTRAP.encode())
        manifest["guard"] = _ref(output, guard)
        for command in plan["commands"]:
            name = command["name"]
            receipt: dict[str, Any] = {
                **command,
                "cwd": str(workspace),
                "shell": False,
                "executor": "subprocess.run",
                "inputs_before": _checkpoint(output, f"inputs.{name}.before.json", root),
                "started_at": _now(),
                "returncode": None,
                "execution_error": None,
            }
            stdout, stderr = b"", b""
            try:
                completed = subprocess.run(
                    command["argv"],
                    cwd=workspace,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    check=False,
                    timeout=command["timeout_seconds"],
                    env=_environment(workspace, output, guarded=name == "pytest"),
                )
                receipt["returncode"] = completed.returncode
                stdout, stderr = completed.stdout, completed.stderr
            except subprocess.TimeoutExpired as exc:
                receipt["execution_error"] = "timeout"
                stdout, stderr = exc.output or b"", exc.stderr or b""
            except OSError as exc:
                receipt["execution_error"] = type(exc).__name__
            receipt["finished_at"] = _now()
            for label, data in (("stdout", stdout), ("stderr", stderr)):
                path = output / f"commands/{name}.{label}.txt"
                _write(path, data)
                receipt[label] = _ref(output, path)
            if name == "pytest":
                receipt["reports"] = {
                    label: _ref(output, output / filename)
                    if (output / filename).is_file()
                    else None
                    for label, filename in (("junit", "junit.xml"), ("coverage", "coverage.json"))
                }
            receipt["inputs_after"] = _checkpoint(output, f"inputs.{name}.after.json", root)
            receipt["workspace_after"] = _checkpoint(
                output, f"workspace.{name}.after.json", workspace
            )
            manifest["commands"].append(_save(output, f"commands/{name}.receipt.json", receipt))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        manifest["errors"].append({"type": type(exc).__name__, "reason": str(exc)})
    finally:
        manifest["inputs_after"] = _checkpoint(output, "inputs.after.json", root)
        manifest["workspace_after"] = _checkpoint(output, "workspace.after.json", workspace)
        manifest["finished_at"] = _now()
    sealed = _save(output, "manifest.json", manifest)
    return validate_verification_bundle(output, expected_manifest_sha256=sealed["sha256"])


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _read_json(data: bytes) -> dict[str, Any]:
    value = json.loads(data, object_pairs_hook=_unique_object)
    _require(isinstance(value, dict), "json_object_required")
    return dict(value)


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    _require(
        bool(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
        and ":" not in value,
        "unsafe_artifact_path",
    )
    _require(path.as_posix() == value and value != ".", "noncanonical_artifact_path")
    return path


def _artifact(root: Path, reference: dict[str, Any], expected: str) -> bytes:
    _require(reference["path"] == expected, "artifact_path_mismatch")
    _require(
        type(reference["size"]) is int and reference["size"] >= 0 and _digest(reference["sha256"]),
        "invalid_artifact_reference",
    )
    path = root / _relative(reference["path"])
    _no_links(path)
    _require(path.resolve(strict=True).is_relative_to(root), "artifact_outside_bundle")
    data = path.read_bytes()
    _require(
        len(data) == reference["size"] and _sha(data) == reference["sha256"],
        "artifact_hash_mismatch",
    )
    return data


def _validate_inputs(value: dict[str, Any]) -> str:
    files = value["files"]
    _require(isinstance(files, list) and files, "empty_input_manifest")
    names = []
    for item in files:
        path = _relative(item["path"])
        _require(
            any(path.is_relative_to(directory) for directory in (*INPUT_DIRS, "docs"))
            or str(path) in (*REQUIRED_FILES, *OPTIONAL_FILES),
            "input_outside_scope",
        )
        _require(type(item["size"]) is int and item["size"] >= 0, "invalid_input_size")
        _require(_digest(item["sha256"]), "invalid_input_hash")
        names.append(str(path))
    _require(
        names == sorted(set(names)) and all(name in names for name in REQUIRED_FILES),
        "invalid_input_inventory",
    )
    digest = _sha(_json_bytes(files))
    _require(value["sha256"] == digest, "input_manifest_hash_mismatch")
    return digest


def _digest(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    _require(parsed.tzinfo is not None, "timestamp_timezone_missing")
    return parsed


def _junit(data: bytes) -> int:
    _require(
        b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "unsafe_junit_xml"
    )
    root = ElementTree.fromstring(data)
    _require(root.tag in {"testsuites", "testsuite"}, "invalid_junit_root")
    cases = list(root.iter("testcase"))
    _require(bool(cases), "empty_junit")
    _require(
        not any(list(root.iter(tag)) for tag in ("failure", "error", "skipped")),
        "junit_not_clean",
    )
    if root.tag == "testsuites":
        if "tests" in root.attrib:
            _require(int(root.attrib["tests"]) == len(cases), "junit_count_mismatch")
        _require(
            all(int(root.attrib.get(key, "0")) == 0 for key in ("errors", "failures", "skipped")),
            "junit_not_clean",
        )
    suites = list(root.iter("testsuite"))
    _require(bool(suites), "missing_junit_suite")
    for suite in suites:
        _require(
            int(suite.attrib["tests"]) == len(list(suite.iter("testcase"))), "junit_count_mismatch"
        )
        _require(
            all(int(suite.attrib[key]) == 0 for key in ("errors", "failures", "skipped")),
            "junit_not_clean",
        )
    return len(cases)


def _coverage(data: bytes, workspace: Path, inputs: dict[str, Any]) -> float:
    value = _read_json(data)
    _require(
        value["meta"]["branch_coverage"] is True and bool(value["files"]), "missing_branch_coverage"
    )
    source_files = {
        item["path"]
        for item in inputs["files"]
        if item["path"].startswith("src/cloud_expert/") and item["path"].endswith(".py")
    }
    reported_files = set()
    for name in value["files"]:
        path = Path(name)
        path = path if path.is_absolute() else workspace / path
        _require(
            path.resolve().is_relative_to(workspace / "src/cloud_expert"),
            "coverage_file_outside_source",
        )
        reported_files.add(path.resolve().relative_to(workspace).as_posix())
    _require(
        reported_files == source_files and len(reported_files) == len(value["files"]),
        "coverage_source_inventory_mismatch",
    )
    keys = (
        "covered_lines",
        "num_statements",
        "missing_lines",
        "covered_branches",
        "num_branches",
        "missing_branches",
    )
    totals = value["totals"]
    for summary in [totals, *(item["summary"] for item in value["files"].values())]:
        _require(
            all(type(summary[key]) is int and summary[key] >= 0 for key in keys),
            "invalid_coverage_counts",
        )
        _require(
            summary["covered_lines"] + summary["missing_lines"] == summary["num_statements"]
            and summary["covered_branches"] + summary["missing_branches"]
            == summary["num_branches"],
            "inconsistent_coverage_counts",
        )
    _require(
        all(
            totals[key] == sum(item["summary"][key] for item in value["files"].values())
            for key in keys
        ),
        "coverage_totals_mismatch",
    )
    denominator = totals["num_statements"] + totals["num_branches"]
    _require(totals["num_statements"] > 0 and denominator > 0, "empty_coverage")
    measured = 100 * (totals["covered_lines"] + totals["covered_branches"]) / denominator
    reported = float(totals["percent_covered"])
    _require(
        math.isfinite(reported) and abs(measured - reported) < 0.000001,
        "coverage_percentage_mismatch",
    )
    return float(measured)


def validate_verification_bundle(
    output_dir: Path, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    """Recompute the historical verdict, never from a caller's passed flag.

    Before reusing a receipt for a new release, compare snapshot_inputs(current_repo)
    with the returned input_sha256. Later source changes do not rewrite history.
    """
    result: dict[str, Any] = {
        "version": VERSION,
        **LIMITS,
        "passed": False,
        "tests_valid": False,
        "inputs_unchanged": False,
        "status": "invalid",
        "errors": [],
        "manifest_sha256": expected_manifest_sha256,
        "output_dir": str(output_dir),
    }
    try:
        _require(_digest(expected_manifest_sha256), "external_manifest_sha256_required")
        _no_links(output_dir.absolute())
        output = output_dir.resolve(strict=True)
        _no_links(output / "manifest.json")
        data = (output / "manifest.json").read_bytes()
        _require(_sha(data) == expected_manifest_sha256, "manifest_hash_mismatch")
        manifest = _read_json(data)
        _require(
            manifest["version"] == VERSION and manifest["output_dir"] == str(output),
            "bundle_identity_mismatch",
        )
        _require(
            all(manifest[key] == value for key, value in LIMITS.items()),
            "verification_scope_mismatch",
        )
        _require(not manifest["errors"], "execution_incomplete")
        start, end = _timestamp(manifest["started_at"]), _timestamp(manifest["finished_at"])
        _require(start <= end, "invalid_run_timestamps")
        plan = _read_json(_artifact(output, manifest["plan"], "plan.json"))
        commands = _commands(output / "workspace", output, manifest["python"])
        _require(
            plan["commands"] == commands and len(manifest["commands"]) == len(commands),
            "fixed_commands_missing_or_changed",
        )
        _require(
            _artifact(output, manifest["guard"], "runtime/guard/sitecustomize.py")
            == GUARD_BOOTSTRAP.encode(),
            "offline_guard_changed",
        )
        initial_inputs = _read_json(
            _artifact(output, manifest["inputs_before"], "inputs.before.json")
        )
        baseline = _validate_inputs(initial_inputs)
        checkpoints = [
            (manifest["inputs_after"], "inputs.after.json"),
            (manifest["workspace_before"], "workspace.before.json"),
            (manifest["workspace_after"], "workspace.after.json"),
        ]
        clean_commands = True
        junit, coverage = b"", b""
        for command, reference in zip(commands, manifest["commands"], strict=True):
            name = command["name"]
            receipt = _read_json(_artifact(output, reference, f"commands/{name}.receipt.json"))
            _require(
                all(receipt[key] == value for key, value in command.items()),
                "command_receipt_mismatch",
            )
            _require(
                receipt["cwd"] == str(output / "workspace")
                and receipt["shell"] is False
                and receipt["executor"] == "subprocess.run",
                "execution_receipt_missing",
            )
            a, b = _timestamp(receipt["started_at"]), _timestamp(receipt["finished_at"])
            _require(start <= a <= b <= end, "invalid_command_timestamps")
            start = b
            clean_commands &= (
                type(receipt["returncode"]) is int
                and receipt["returncode"] == 0
                and receipt["execution_error"] is None
            )
            for label in ("stdout", "stderr"):
                _artifact(output, receipt[label], f"commands/{name}.{label}.txt")
            checkpoints.extend(
                (
                    (receipt["inputs_before"], f"inputs.{name}.before.json"),
                    (receipt["inputs_after"], f"inputs.{name}.after.json"),
                    (receipt["workspace_after"], f"workspace.{name}.after.json"),
                )
            )
            if name == "pytest":
                junit = _artifact(output, receipt["reports"]["junit"], "junit.xml")
                coverage = _artifact(output, receipt["reports"]["coverage"], "coverage.json")
        observed = [
            _validate_inputs(_read_json(_artifact(output, reference, name)))
            for reference, name in checkpoints
        ]
        unchanged = all(digest == baseline for digest in observed)
        unchanged &= snapshot_inputs(output / "workspace")["sha256"] == baseline
        result.update(inputs_unchanged=unchanged, input_sha256=baseline)
        count, percent = _junit(junit), _coverage(coverage, output / "workspace", initial_inputs)
        result.update(
            tests=count,
            coverage_percent=percent,
            tests_valid=unchanged and clean_commands and percent >= MIN_COVERAGE,
        )
        if not unchanged:
            result["errors"].append("inputs_changed_during_verification")
        if not clean_commands:
            result["errors"].append("command_failed")
        if percent < MIN_COVERAGE:
            result["errors"].append("coverage_below_85")
        result["passed"] = not result["errors"]
        result["status"] = "passed" if result["passed"] else "failed"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        ElementTree.ParseError,
    ) as exc:
        result["errors"].append(f"invalid_bundle:{exc}")
    return result


def _sqlite_filename(database: str) -> str:
    if not database.startswith("file:"):
        return database
    _require(not any(ord(char) < 32 for char in database), "offline_database_uri_invalid")
    parsed = urlsplit(database)
    decoded = unquote(parsed.path, errors="strict")
    _require(
        not parsed.netloc and not decoded.replace("\\", "/").startswith("//"),
        "offline_database_authority_denied",
    )
    _require(not any(ord(char) < 32 for char in decoded), "offline_database_uri_invalid")
    # url2pathname uses the host's file-URI rules, including /D:/ on Windows.
    return url2pathname(parsed.path)


def _windows_child_argv(command_line: str) -> list[str]:
    import ctypes

    _require(os.name == "nt" and bool(command_line), "offline_child_argv_invalid")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    split = shell32.CommandLineToArgvW
    split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    free = kernel32.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    count = ctypes.c_int()
    pointer = split(command_line, ctypes.byref(count))
    _require(bool(pointer), "offline_child_argv_invalid")
    try:
        argv = [str(pointer[index]) for index in range(count.value)]
    finally:
        free(pointer)
    # Accept Popen's list2cmdline representation, not ambiguous shell-style strings.
    _require(subprocess.list2cmdline(argv) == command_line, "offline_child_argv_invalid")
    return argv


def _python_child_argv(executable: Any, arguments: Any, python: Path) -> list[str]:
    if isinstance(arguments, str):
        argv = _windows_child_argv(arguments)
    else:
        _require(isinstance(arguments, (list, tuple)), "offline_child_argv_invalid")
        _require(
            all(isinstance(arg, (str, bytes, os.PathLike)) for arg in arguments),
            "offline_child_argv_invalid",
        )
        argv = [os.fsdecode(arg) for arg in arguments]
    _require(bool(argv) and all("\x00" not in arg for arg in argv), "offline_child_argv_invalid")
    # Windows reports executable=None when CreateProcess uses argv[0].
    executable = argv[0] if executable is None else executable
    _require(isinstance(executable, (str, bytes, os.PathLike)), "offline_non_python_child_denied")
    for value in (os.fsdecode(executable), argv[0]):
        path = Path(value)
        _require(path.is_absolute() and path.resolve() == python, "offline_non_python_child_denied")
    for argument in argv[1:]:
        if argument in {"-c", "-m", "-", "--"} or not argument.startswith("-"):
            break
        # Keep startup parsing bounded; in particular -I/-E/-S cannot hide in a cluster.
        _require(
            argument in {"-B", "-u", "-b", "-bb", "-O", "-OO", "-q", "-s", "-v", "-vv", "-P"},
            "offline_child_guard_disabled",
        )
    return argv


def install_offline_guard() -> None:
    """Guard the isolated pytest interpreter and its Python children, not an OS sandbox."""
    inherited = _canonical_environment(os.environ)
    root_value = inherited.get("CLOUD_EXPERT_VERIFICATION_ROOT")
    _require(root_value, "offline_guard_root_missing")
    root = Path(str(root_value)).resolve(strict=True)
    python = Path(sys.executable).resolve()
    pythonpath = inherited.get("PYTHONPATH")

    def allowed_write(value: Any) -> None:
        if isinstance(value, int) or value is None:
            return
        path = Path(os.fsdecode(value))
        _require(
            path.resolve() == Path(os.devnull).resolve() or path.resolve().is_relative_to(root),
            "offline_write_outside_output",
        )

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event in {
            "socket.connect",
            "socket.connect_ex",
            "socket.bind",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "os.system",
            "os.exec",
            "os.posix_spawn",
        }:
            raise PermissionError("offline_network_or_external_execution_denied")
        if (
            event == "open"
            and isinstance(args[2], int)
            and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ):
            allowed_write(args[0])
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.truncate", "os.utime"}:
            allowed_write(args[0])
        if event in {"os.rename", "os.link", "os.symlink"}:
            allowed_write(args[0])
            allowed_write(args[1])
        if event == "sqlite3.connect":
            database = os.fsdecode(args[0])
            if database != ":memory:":
                allowed_write(_sqlite_filename(database))
        if event == "subprocess.Popen":
            executable, argv, _, environment = args
            environment = _canonical_environment(os.environ if environment is None else environment)
            _python_child_argv(executable, argv, python)
            _require(
                environment.get("CLOUD_EXPERT_VERIFICATION_ROOT") == str(root)
                and environment.get("PYTHONPATH") == pythonpath,
                "offline_child_guard_missing",
            )

    sys.addaudithook(audit)
