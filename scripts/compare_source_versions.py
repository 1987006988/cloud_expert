import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.config.settings import get_settings
from cloud_expert.ingestion.change_detection.detector import detect_change
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare source versions.")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()

    entry = get_entry_by_source_id(args.source_id, args.registry_dir)
    if entry is None:
        print(f"Unknown source_id: {args.source_id}")
        return 1
    store = SnapshotStore(Path(get_settings().raw_data_dir))
    root = store.source_root(entry)
    manifest_paths = sorted(root.rglob("manifest.json")) if root.exists() else []
    if len(manifest_paths) < 2:
        print(
            json.dumps(
                {
                    "source_id": args.source_id,
                    "previous_snapshot_id": None,
                    "current_snapshot_id": None,
                    "change_status": "unknown",
                    "changes": [],
                    "reason": "Need at least two snapshots to compare.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    current = store.load_manifest(manifest_paths[-1])
    previous = store.load_manifest(manifest_paths[-2])
    report = detect_change(entry.source_id, current, previous)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
