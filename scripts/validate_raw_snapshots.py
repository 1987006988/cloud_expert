import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cloud_expert.config.settings import get_settings
from cloud_expert.ingestion.security.headers import (
    SENSITIVE_HEADER_KEYWORDS,
    SENSITIVE_HEADER_NAMES,
)
from cloud_expert.ingestion.security.path_safety import ensure_relative_safe_path
from cloud_expert.ingestion.storage.hashing import sha256_hex
from cloud_expert.ingestion.storage.manifest import SnapshotManifest


def _validate_manifest(raw_root: Path, manifest_path: Path) -> list[str]:
    errors: list[str] = []
    manifest = SnapshotManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    for relative in (
        manifest.storage_path,
        manifest.response_headers_path,
        manifest.metadata_path,
    ):
        try:
            ensure_relative_safe_path(relative)
        except ValueError as exc:
            errors.append(str(exc))
    raw_path = raw_root / manifest.storage_path
    if not raw_path.exists():
        errors.append(f"raw file missing: {manifest.storage_path}")
    elif sha256_hex(raw_path.read_bytes()) != manifest.content_sha256:
        errors.append(f"hash mismatch: {manifest_path}")
    headers_path = raw_root / manifest.response_headers_path
    if headers_path.exists():
        headers = json.loads(headers_path.read_text(encoding="utf-8"))
        for name, value in headers.items():
            lower_name = name.lower()
            if (
                lower_name in SENSITIVE_HEADER_NAMES
                or any(keyword in lower_name for keyword in SENSITIVE_HEADER_KEYWORDS)
            ) and value != "[REDACTED]":
                errors.append(f"sensitive header not redacted: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate raw snapshot manifests and files.")
    parser.add_argument("--raw-dir", type=Path, default=None)
    args = parser.parse_args()

    raw_root = (args.raw_dir or Path(get_settings().raw_data_dir)).resolve()
    manifests = sorted(raw_root.rglob("manifest.json")) if raw_root.exists() else []
    errors: list[str] = []
    for manifest_path in manifests:
        errors.extend(_validate_manifest(raw_root, manifest_path))
    for latest_path in raw_root.rglob("latest.json") if raw_root.exists() else []:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        manifest_relative = latest.get("manifest_path")
        if not isinstance(manifest_relative, str):
            errors.append(f"latest missing manifest_path: {latest_path}")
            continue
        try:
            ensure_relative_safe_path(manifest_relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not (raw_root / manifest_relative).exists():
            errors.append(f"latest points to missing manifest: {latest_path}")
    for tmp_path in raw_root.rglob("*.tmp") if raw_root.exists() else []:
        errors.append(f"temporary file remains: {tmp_path}")
    summary = {
        "snapshots_checked": len(manifests),
        "errors": len(errors),
        "details": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
