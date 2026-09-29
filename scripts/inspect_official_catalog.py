"""Inspect an existing authorized snapshot offline; stdout only, never writes a DB."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.ingestion.exceptions import ConfigurationError
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.pricing.official_catalog import (
    MAX_BYTES,
    CatalogSelection,
    decode_catalog_json,
    inspect_official_catalog,
)


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input exceeds inspection size limit")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--selection", type=Path, required=True, help="JSON array of CatalogSelection"
    )
    parser.add_argument("--max-age-days", type=int, required=True)
    parser.add_argument("--as-of", help="Aware ISO timestamp; defaults to current UTC")
    args = parser.parse_args()
    try:
        manifest = decode_catalog_json(_read(args.manifest, 65_536), limit=65_536)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("storage_path"), str):
            raise ValueError("snapshot manifest with storage_path required")
        root = args.raw_root.resolve()
        raw_path = (root / manifest["storage_path"]).resolve()
        if not raw_path.is_relative_to(root):
            raise ValueError("snapshot path escapes raw root")
        selected = decode_catalog_json(_read(args.selection, 65_536), limit=65_536)
        if not isinstance(selected, list):
            raise ValueError("selection must be a JSON array")
        entry = get_entry_by_source_id(args.source_id)
        if entry is None:
            raise ValueError("source is not registered")
        result = inspect_official_catalog(
            _read(raw_path, MAX_BYTES),
            entry=entry,
            manifest=manifest,
            selections=[CatalogSelection.model_validate(row) for row in selected],
            as_of=datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC),
            max_age_days=args.max_age_days,
        )
    except (ValueError, OSError, ConfigurationError) as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc), "database_write_performed": False})
        )
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
