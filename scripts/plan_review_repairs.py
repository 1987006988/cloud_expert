from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy.exc import SQLAlchemyError

from cloud_expert.model_review.repair_inventory import inventory_from_sqlite

ROOT = Path(__file__).resolve().parents[1]


def write_report(manifest: dict[str, Any], directory: Path, database: Path) -> dict[str, Any]:
    """Create-only report files; incomplete attempts remain for investigation."""
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError(f"Report directory is not empty: {directory}")
    payload = (json.dumps(manifest, ensure_ascii=True, indent=2, default=str) + "\n").encode(
        "utf-8"
    )
    metadata = {
        "schema_version": "1.0",
        "status": "complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
        "database_path": str(database.resolve()),
        "planner_version": manifest["planner_version"],
        "plan_id": manifest["plan_id"],
        "source_snapshot_hash": manifest["source_snapshot_hash"],
        "manifest_file": "manifest.json",
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "manifest_bytes": len(payload),
        "dry_run": True,
        "database_writeback": False,
        "approvals_granted": 0,
        "gate_updated": False,
        "summary": manifest["summary"],
        "limits": manifest["limits"],
    }
    # Exclusive creation also arbitrates concurrent writers that both saw an empty directory.
    with (directory / "manifest.json").open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    with (directory / "summary.json").open("xb") as handle:
        handle.write((json.dumps(metadata, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only review root-cause and disposition plan."
    )
    parser.add_argument(
        "--database", type=Path, default=ROOT / "test_outputs/week6_combined_projection.sqlite"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Required acknowledgement; there is deliberately no apply mode.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print counts without per-object manifest."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Create full manifest.json and summary.json; refuse an existing nonempty directory.",
    )
    args = parser.parse_args()
    report_metadata = None
    try:
        manifest = inventory_from_sqlite(args.database)
        if args.output_dir is not None:
            report_metadata = write_report(manifest, args.output_dir, args.database)
    except (OSError, ValueError, SQLAlchemyError) as exc:
        parser.exit(2, f"Inventory unavailable: {exc}\n")
    if args.summary:
        manifest = {
            key: manifest[key]
            for key in (
                "planner_version",
                "plan_id",
                "dry_run",
                "database_writeback",
                "approvals_granted",
                "gate_updated",
                "source_snapshot_hash",
                "summary",
                "groups",
                "limits",
            )
        }
    if report_metadata is not None:
        manifest = {
            **manifest,
            "report_directory": str(args.output_dir.resolve()),
            "report_manifest_sha256": report_metadata["manifest_sha256"],
        }
    print(json.dumps(manifest, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
