import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.config.settings import get_settings
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Show source snapshot history.")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--registry-dir", type=Path, default=None)
    args = parser.parse_args()

    entry = get_entry_by_source_id(args.source_id, args.registry_dir)
    if entry is None:
        print(f"Unknown source_id: {args.source_id}")
        return 1
    store = SnapshotStore(Path(get_settings().raw_data_dir))
    root = store.source_root(entry)
    manifests = []
    for path in sorted(root.rglob("manifest.json")) if root.exists() else []:
        manifests.append(store.load_manifest(path).model_dump(mode="json"))
    print(json.dumps(manifests, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
