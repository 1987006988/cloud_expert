"""Dry-run OSS evidence planning; explicit coordinator-only --apply commits to env DB."""

from __future__ import annotations

import argparse
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401

from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing.oss_capture import (
    SOURCE_ID,
    apply_oss_capture,
    plan_oss_capture,
    read_oss_capture,
)


def _write_new(path: Path, result: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=True, indent=2) + "\n")


def _apply_to_env(args: argparse.Namespace, as_of: datetime) -> dict[str, Any]:
    # No environment database is imported or opened by the default dry-run path.
    from cloud_expert.database.session import SessionLocal

    with SessionLocal() as session:
        return apply_oss_capture(
            session,
            args.capture,
            expected_sha256=args.expected_sha256,
            previous_plan_sha256=args.previous_plan_sha256,
            as_of=as_of,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--as-of", help="Aware timestamp; defaults to current UTC")
    parser.add_argument("--report", type=Path, help="Optional new report path; never overwritten")
    parser.add_argument("--report-dir", type=Path, help="New exclusive directory for plan/result")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Coordinator only: commit snapshot/Evidence, never Price",
    )
    parser.add_argument("--previous-plan-sha256", help="plan_sha256 returned by a prior dry run")
    args = parser.parse_args()
    if args.report and args.report_dir:
        parser.error("choose --report or --report-dir")
    if args.apply and (not args.report_dir or not args.previous_plan_sha256):
        parser.error("--apply requires --previous-plan-sha256 and a new --report-dir")
    committed = False
    report_dir_created = False
    try:
        if args.report and args.report.resolve() == args.capture.resolve():
            raise ValueError("report cannot replace capture")
        entry = get_entry_by_source_id(SOURCE_ID)
        if entry is None:
            raise ValueError("OSS source is not registered")
        as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
        result = plan_oss_capture(
            read_oss_capture(args.capture),
            entry=entry,
            expected_sha256=args.expected_sha256,
            as_of=as_of,
        )
        if args.apply and result["plan_sha256"] != args.previous_plan_sha256:
            raise ValueError("previous plan hash differs from current validated plan")
        if args.report_dir:
            args.report_dir.mkdir(exist_ok=False)
            report_dir_created = True
            _write_new(args.report_dir / "plan.json", result)
        if args.apply:
            result = _apply_to_env(args, as_of)
            committed = True
            _write_new(args.report_dir / "result.json", result)
        rendered = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
        if args.report:
            _write_new(args.report, result)
    except Exception as exc:
        # Do not echo rejected input, credentials or sensitive validation details.
        failure = {
            "status": "committed_report_failure" if committed else "blocked",
            "error_type": type(exc).__name__,
            "database_commit_completed": committed,
            "database_write_performed": committed,
            "immutable_raw_files_may_remain_after_rollback": bool(args.apply),
        }
        if report_dir_created:
            with suppress(OSError):
                _write_new(args.report_dir / "failure.json", failure)
        print(json.dumps(failure))
        return 1
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
