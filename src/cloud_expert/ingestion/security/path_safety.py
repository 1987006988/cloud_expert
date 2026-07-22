import re
from pathlib import Path

SAFE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    normalized = normalized.strip("._-") or "unknown"
    if len(normalized) > 128:
        normalized = normalized[:128].rstrip("._-")
    if not SAFE_SEGMENT_PATTERN.match(normalized):
        msg = f"unsafe path segment: {value!r}"
        raise ValueError(msg)
    return normalized


def ensure_relative_safe_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        msg = f"path must be safe and relative: {path}"
        raise ValueError(msg)
    for part in candidate.parts:
        safe_path_segment(part)
    return candidate


def ensure_within_directory(base_dir: Path, target: Path) -> Path:
    base = base_dir.resolve()
    resolved = target.resolve()
    if base != resolved and base not in resolved.parents:
        msg = f"target path escapes base directory: {target}"
        raise ValueError(msg)
    return resolved
