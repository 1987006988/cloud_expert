"""Read explicit historical receipts; never select reports or update a Gate.

``valid`` describes the supplied evidence only. Consumers requiring a current
release must also require ``current_code_verified``. Neither result is a
full-chain Eval, customer authorization, or proof of production readiness.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict
from xml.etree import ElementTree

import yaml

from cloud_expert.evals import verification_run

EXPECTED_HEAD = "0014_week14_review_workflow"
EXPECTED_PREVIOUS = "0013_week12_market_context"
EXPECTED_POSTGRES_TEST_IDS: frozenset[str] = frozenset(
    {
        "tests.integration.test_postgres_market::test_market_context_uses_jsonb_constraints_and_transaction_rollback",
        "tests.integration.test_postgres_model_review::test_model_review_queue_jsonb_constraints_and_rollback",
        "tests.integration.test_postgres_price_lifecycle::test_postgres_price_replacement_atomic_rollback_and_idempotence",
        "tests.integration.test_postgres_price_lifecycle::test_postgres_conflicting_connection_locks_then_retries_idempotently",
        "tests.integration.test_postgres_price_quarantine::test_postgres_quarantine_atomic_rollback_and_idempotence",
        "tests.integration.test_postgres_price_quarantine::test_postgres_quarantine_partial_append_rolls_back",
        "tests.integration.test_postgres_price_quarantine::test_postgres_quarantine_competing_connection_locks_then_retries",
        "tests.integration.test_postgres_price_quarantine::test_postgres_quarantine_competing_plans_reject_stale_audit",
        "tests.integration.test_postgres_r011::test_schema_has_expected_postgresql_types_and_constraints",
        "tests.integration.test_postgres_r011::test_check_constraint_enforces_enum_like_values",
        "tests.integration.test_postgres_r011::test_numeric_decimal_json_and_timezone_behavior",
        "tests.integration.test_postgres_r011::test_foreign_key_and_unique_constraints",
        "tests.integration.test_postgres_r011::test_transaction_rollback_leaves_no_partial_snapshot_chain",
        "tests.integration.test_postgres_r011::test_concurrent_provider_creation_respects_unique_idempotency_boundary",
    }
)

MigrationStep = Literal[
    "fresh_upgrade", "downgrade_one", "reupgrade_one", "downgrade_base", "reupgrade_base"
]
MIGRATION_STEPS: tuple[MigrationStep, ...] = (
    "fresh_upgrade",
    "downgrade_one",
    "reupgrade_one",
    "downgrade_base",
    "reupgrade_base",
)


@dataclass(frozen=True)
class CommandReceipt:
    """Explicit artifact and observed exit code, supplied by the coordinator.

    Do not infer a zero exit code merely because an Alembic log has no errors.
    These unsealed inputs are recorded as caller assertions, not authenticated.
    """

    path: Path
    returncode: int


class ReceiptResult(TypedDict):
    valid: bool
    current_code_verified: bool
    code_fingerprint_status: Literal["current", "stale", "unavailable", "not_recorded"]
    full_chain_eval: Literal[False]
    scope: str
    errors: list[str]
    warnings: list[str]
    provenance: dict[str, Any]
    metrics: dict[str, Any]


def _result(scope: str) -> ReceiptResult:
    return {
        "valid": False,
        "current_code_verified": False,
        "code_fingerprint_status": "not_recorded",
        "full_chain_eval": False,
        "scope": scope,
        "errors": [],
        "warnings": [],
        "provenance": {},
        "metrics": {},
    }


def read_offline_bundle(
    bundle_dir: Path, *, expected_manifest_sha256: str, current_repo: Path
) -> ReceiptResult:
    """Require the runner's independently retained SHA, never read a local SHA sidecar.

    A valid but stale bundle remains historical evidence and explicitly cannot
    certify the current checkout. Fingerprints include uncommitted inputs.
    """
    result = _result("sealed_offline_verification")
    verified = verification_run.validate_verification_bundle(
        bundle_dir, expected_manifest_sha256=expected_manifest_sha256
    )
    result["valid"] = verified["passed"] is True
    result["errors"] = list(verified["errors"])
    result["provenance"] = {
        "bundle_dir": str(bundle_dir.absolute()),
        "expected_manifest_sha256": expected_manifest_sha256,
        "manifest_trust_anchor": "caller_supplied_independent_sha256",
        "input_sha256": verified.get("input_sha256"),
        "current_repo": str(current_repo.absolute()),
        "verifier": "cloud_expert.evals.verification_run.validate_verification_bundle",
        "verification": verified,
    }
    result["metrics"] = {
        "tests": verified.get("tests"),
        "coverage_percent": verified.get("coverage_percent"),
    }
    result["code_fingerprint_status"] = "unavailable"
    if not result["valid"]:
        return result
    try:
        current = verification_run.snapshot_inputs(current_repo)["sha256"]
    except (OSError, ValueError) as exc:
        result["warnings"].append(f"current_fingerprint_unavailable:{exc}")
        return result
    result["provenance"]["current_input_sha256"] = current
    result["current_code_verified"] = current == verified["input_sha256"]
    result["code_fingerprint_status"] = "current" if result["current_code_verified"] else "stale"
    if not result["current_code_verified"]:
        result["warnings"].append("stale_code_fingerprint:historical_receipt_only")
    return result


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _read_command(receipt: CommandReceipt, provenance: dict[str, Any]) -> bytes:
    path = receipt.path.absolute()
    provenance.update(path=str(path), returncode=receipt.returncode)
    _require(type(receipt.returncode) is int and receipt.returncode == 0, "command_not_successful")
    for part in (path, *path.parents):
        _require(not part.is_symlink() and not part.is_junction(), "linked_receipt_rejected")
    _require(path.is_file(), "receipt_not_regular_file")
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    _require(
        (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        "receipt_changed_while_reading",
    )
    provenance.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return data


def _postgres_junit(data: bytes, expected_test_ids: frozenset[str]) -> list[str]:
    _require(bool(expected_test_ids), "expected_postgres_tests_required")
    text = data.decode("utf-8-sig")
    _require("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(), "unsafe_junit_xml")
    root = ElementTree.fromstring(text)
    _require(root.tag in {"testsuites", "testsuite"}, "invalid_junit_root")
    suites = list(root) if root.tag == "testsuites" else [root]
    _require(bool(suites) and all(s.tag == "testsuite" for s in suites), "invalid_junit_suites")
    _require(
        not any(list(root.iter(tag)) for tag in ("failure", "error", "skipped")),
        "junit_not_clean",
    )
    ids = []
    for suite in suites:
        _require(
            not list(suite.iter("testsuites")) and not suite.findall("testsuite"), "nested_suite"
        )
        cases = suite.findall("testcase")
        _require(bool(cases) and int(suite.attrib["tests"]) == len(cases), "junit_count_mismatch")
        _require(
            all(suite.attrib[key] == "0" for key in ("errors", "failures", "skipped")),
            "junit_not_clean",
        )
        for case in cases:
            classname, name = case.attrib["classname"], case.attrib["name"]
            _require(
                re.fullmatch(r"tests\.integration\.test_postgres_[A-Za-z0-9_]+", classname)
                and name.startswith("test_"),
                "non_postgres_test",
            )
            ids.append(f"{classname}::{name}")
    _require(len(ids) == len(set(ids)), "duplicate_test_identity")
    _require(set(ids) == expected_test_ids, "postgres_test_inventory_mismatch")
    _require(len(list(root.iter("testcase"))) == len(ids), "unaccounted_testcase")
    if root.tag == "testsuites":
        _require(
            "tests" not in root.attrib or int(root.attrib["tests"]) == len(ids),
            "junit_count_mismatch",
        )
        _require(
            all(root.attrib.get(key, "0") == "0" for key in ("errors", "failures", "skipped")),
            "junit_not_clean",
        )
    return sorted(ids)


def _migration_transitions(data: bytes, direction: str) -> list[tuple[str, str]]:
    text = data.decode("utf-8-sig")
    _require("Context impl PostgresqlImpl." in text, "postgres_migration_context_missing")
    _require(
        not re.search(r"\b(?:ERROR|CRITICAL|FATAL|Traceback|FAILED)\b", text, re.IGNORECASE),
        "migration_error_in_log",
    )
    _require(
        set(re.findall(r"Context impl ([A-Za-z0-9_]+)\.", text)) == {"PostgresqlImpl"},
        "mixed_migration_context",
    )
    transitions = []
    for line in text.splitlines():
        if "Running upgrade" not in line and "Running downgrade" not in line:
            continue
        match = re.fullmatch(
            r"INFO\s+\[alembic\.runtime\.migration\] Running (upgrade|downgrade) "
            r"([A-Za-z0-9_]*) -> ([A-Za-z0-9_]*),.*",
            line.strip(),
        )
        _require(match is not None, "unrecognized_migration_transition")
        assert match is not None
        _require(match[1] == direction, "wrong_migration_direction")
        transitions.append((match[2], match[3]))
    _require(bool(transitions), "migration_transitions_missing")
    _require(
        all(a != b for a, b in transitions)
        and all(
            left[1] == right[0] for left, right in zip(transitions, transitions[1:], strict=False)
        ),
        "migration_chain_discontinuous",
    )
    return transitions


def read_postgres_receipts(
    junit: CommandReceipt,
    *,
    migrations: Mapping[MigrationStep, CommandReceipt],
    expected_test_ids: frozenset[str],
    expected_head: str,
    expected_previous: str,
) -> ReceiptResult:
    """Validate exact PostgreSQL tests and five explicit migration command receipts.

    Logs/JUnit are unsigned historical evidence, not execution authentication.
    No code fingerprint is present, so current-code certification stays false.
    Exit codes must come from actual execution records, never guessed from logs.
    """
    result = _result("postgres_junit_and_migration_receipts")
    result["warnings"] = ["unsigned_caller_supplied_receipts", "code_fingerprint_not_recorded"]
    result["provenance"] = {
        "execution_authenticated": False,
        "expected_head": expected_head,
        "expected_previous": expected_previous,
        "expected_test_ids": sorted(expected_test_ids),
        "junit": {},
        "migrations": {},
    }
    try:
        _require(
            re.fullmatch(r"[A-Za-z0-9_]+", expected_head)
            and re.fullmatch(r"[A-Za-z0-9_]+", expected_previous)
            and expected_head != expected_previous,
            "explicit_distinct_migration_revisions_required",
        )
        _require(set(migrations) == set(MIGRATION_STEPS), "explicit_migration_receipts_required")
        paths = [receipt.path.resolve() for receipt in (junit, *migrations.values())]
        _require(len(set(paths)) == len(paths), "duplicate_receipt_path")
        ids = _postgres_junit(
            _read_command(junit, result["provenance"]["junit"]), expected_test_ids
        )
        result["metrics"].update(tests=len(ids), test_ids=ids)
        transitions = {}
        for step in MIGRATION_STEPS:
            provenance: dict[str, Any] = {}
            result["provenance"]["migrations"][step] = provenance
            data = _read_command(migrations[step], provenance)
            direction = "downgrade" if step.startswith("downgrade") else "upgrade"
            transitions[step] = _migration_transitions(data, direction)
            provenance["transitions"] = transitions[step]
        fresh = transitions["fresh_upgrade"]
        _require(
            fresh[0][0] == "" and fresh[-1] == (expected_previous, expected_head),
            "fresh_upgrade_endpoints_mismatch",
        )
        revisions = [fresh[0][0], *(target for _, target in fresh)]
        _require(len(set(revisions)) == len(revisions), "migration_cycle")
        _require(transitions["reupgrade_base"] == fresh, "base_reupgrade_mismatch")
        _require(
            transitions["downgrade_base"] == [(b, a) for a, b in reversed(fresh)],
            "base_downgrade_mismatch",
        )
        _require(
            transitions["downgrade_one"] == [(expected_head, expected_previous)]
            and transitions["reupgrade_one"] == [(expected_previous, expected_head)],
            "one_step_roundtrip_mismatch",
        )
        result["valid"] = True
    except (OSError, ValueError, KeyError, TypeError, ElementTree.ParseError) as exc:
        result["errors"].append(f"invalid_postgres_receipts:{exc}")
    return result


class _ReceiptLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        value = super().construct_mapping(node, deep=deep)
        _require(len(value) == len(node.value), "duplicate_receipt_key")
        return value


def read_gate_receipts(
    context_path: Path,
    current_repo: Path,
    expected_test_ids: frozenset[str],
    expected_head: str,
    expected_previous: str,
) -> dict[str, ReceiptResult]:
    """Read operational YAML pointers; all relative paths are repository-relative.

    The coordinator independently records manifest SHAs in the context. Expected
    test identities and Alembic revisions must come from the gate's known scope,
    never from these reports. No Alembic execution or report discovery occurs.
    """
    results = {
        "coverage": _result("sealed_offline_verification"),
        "postgres": _result("postgres_junit_and_migration_receipts"),
    }
    artifact_hashes: dict[str, str] = {}

    def path(value: Any) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("receipt_path_required")
        return current_repo / value

    def read(file: Path) -> bytes:
        return _read_command(CommandReceipt(file, 0), {})

    def command(value: Any) -> CommandReceipt:
        _require(
            isinstance(value, dict) and set(value) == {"path", "returncode", "sha256"},
            "invalid_command_receipt",
        )
        _require(re.fullmatch(r"[0-9a-f]{64}", value["sha256"]), "artifact_sha256_required")
        file = path(value["path"])
        artifact_hashes[str(file.absolute())] = value["sha256"]
        return CommandReceipt(file, value["returncode"])

    context_file = current_repo / context_path
    context_data = b""
    try:
        context_data = read(context_file)
        context = yaml.load(context_data.decode("utf-8-sig"), Loader=_ReceiptLoader)
        _require(
            isinstance(context, dict) and set(context) == {"offline_bundle", "postgres"},
            "invalid_receipt_context",
        )
        for key, location in (("offline_bundle", "path"), ("postgres", "manifest_path")):
            pointer = context[key]
            _require(
                isinstance(pointer, dict) and set(pointer) == {location, "sha256"},
                "invalid_receipt_pointer",
            )
            _require(
                re.fullmatch(r"[0-9a-f]{64}", pointer["sha256"]),
                "independent_manifest_sha256_required",
            )
        manifest_path = path(context["postgres"]["manifest_path"])
        manifest_data = read(manifest_path)
        _require(
            hashlib.sha256(manifest_data).hexdigest() == context["postgres"]["sha256"],
            "postgres_manifest_hash_mismatch",
        )
        # The same strict loader rejects duplicate keys in JSON as well as YAML.
        json.loads(manifest_data)
        manifest = yaml.load(manifest_data.decode("utf-8-sig"), Loader=_ReceiptLoader)
        _require(isinstance(manifest, dict), "invalid_postgres_manifest")
        _require(
            isinstance(manifest["expected_test_ids"], list)
            and sorted(manifest["expected_test_ids"]) == sorted(expected_test_ids),
            "postgres_manifest_test_scope_mismatch",
        )
        _require(
            manifest["expected_head"] == expected_head
            and manifest["expected_previous"] == expected_previous,
            "postgres_manifest_revision_scope_mismatch",
        )
        bound = manifest["repository_input_sha256"]
        _require(re.fullmatch(r"[0-9a-f]{64}", bound), "repository_input_sha256_required")
        _require(
            manifest["inputs_unchanged"] is True
            and manifest["input_sha256_before"] == manifest["input_sha256_after"] == bound,
            "postgres_inputs_changed_during_execution",
        )
        _require(
            isinstance(manifest["migrations"], dict)
            and set(manifest["migrations"]) == set(MIGRATION_STEPS),
            "explicit_migration_receipts_required",
        )
        results["coverage"] = read_offline_bundle(
            path(context["offline_bundle"]["path"]),
            expected_manifest_sha256=context["offline_bundle"]["sha256"],
            current_repo=current_repo,
        )
        pg = read_postgres_receipts(
            command(manifest["junit"]),
            migrations={step: command(manifest["migrations"][step]) for step in MIGRATION_STEPS},
            expected_test_ids=expected_test_ids,
            expected_head=expected_head,
            expected_previous=expected_previous,
        )
        results["postgres"] = pg
        if pg["valid"]:
            for artifact in [pg["provenance"]["junit"], *pg["provenance"]["migrations"].values()]:
                _require(
                    artifact["sha256"] == artifact_hashes[artifact["path"]],
                    "postgres_artifact_hash_mismatch",
                )
        current = verification_run.snapshot_inputs(current_repo)["sha256"]
        _require(
            results["coverage"]["provenance"].get("current_input_sha256", current) == current,
            "repository_inputs_changed_during_read",
        )
        pg["provenance"].update(
            manifest_path=str(manifest_path.absolute()),
            expected_manifest_sha256=context["postgres"]["sha256"],
            input_sha256=bound,
            current_input_sha256=current,
            manifest_trust_anchor="coordinator_independent_sha256_in_context",
            inputs_unchanged=True,
            input_sha256_before=manifest["input_sha256_before"],
            input_sha256_after=manifest["input_sha256_after"],
        )
        pg["warnings"].remove("code_fingerprint_not_recorded")
        pg["code_fingerprint_status"] = "unavailable"
        if pg["valid"]:
            pg["current_code_verified"] = bound == current
            pg["code_fingerprint_status"] = "current" if bound == current else "stale"
            if bound != current:
                pg["warnings"].append("stale_code_fingerprint:historical_receipt_only")
        _require(context_data == read(context_file), "receipt_context_changed_during_read")
        _require(manifest_data == read(manifest_path), "postgres_manifest_changed_during_read")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        for result in results.values():
            result.update(
                {
                    "valid": False,
                    "current_code_verified": False,
                    "code_fingerprint_status": "unavailable",
                }
            )
            result["errors"].append(f"invalid_gate_receipts:{exc}")
    for result in results.values():
        result["provenance"].update(
            context_path=str(context_file.absolute()),
            context_sha256=hashlib.sha256(context_data).hexdigest() if context_data else None,
        )
    return results
