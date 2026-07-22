from pathlib import Path
from typing import Any

import yaml

from cloud_expert.config.settings import get_settings
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry, parse_registry_entry


def load_yaml_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        msg = f"registry file must contain a mapping: {path}"
        raise ValueError(msg)
    return data


def iter_registry_files(registry_dir: Path | None = None) -> list[Path]:
    base_dir = registry_dir or Path(get_settings().source_registry_dir)
    if not base_dir.exists():
        return []
    return sorted(path for path in base_dir.rglob("*.yaml") if path.is_file())


def load_registry_entries(registry_dir: Path | None = None) -> list[SourceRegistryEntry]:
    entries: list[SourceRegistryEntry] = []
    for path in iter_registry_files(registry_dir):
        entries.append(parse_registry_entry(load_yaml_file(path), registry_file=path))
    return entries


def get_entry_by_source_id(
    source_id: str, registry_dir: Path | None = None
) -> SourceRegistryEntry | None:
    for entry in load_registry_entries(registry_dir):
        if entry.source_id == source_id:
            return entry
    return None
