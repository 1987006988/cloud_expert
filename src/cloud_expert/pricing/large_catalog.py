"""Offline, bounded EC2 catalog selection from an already retained raw snapshot.

This does not authorize acquisition or relax FetchPolicy. The caller supplies
trusted SnapshotStore metadata. Only the selected envelope receives semantic
price validation; hashing the entire original is not full-catalog approval.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.pricing.official_catalog import (
    CatalogSelection,
    inspect_official_catalog,
    validate_official_catalog_source,
)

MAX_RAW_BYTES = 512 * 1024 * 1024
MAX_SELECTED_BYTES = 8 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
MAX_TOKEN_BYTES = 64 * 1024
MAX_DEPTH = 64
MAX_ACTIVE_KEYS = 500_000
MAX_ACTIVE_KEY_BYTES = 16 * 1024 * 1024
RULE_VERSION = "aws_ec2_streaming_selection_v2"
_METADATA = {"formatVersion", "offerCode", "version", "publicationDate", "disclaimer"}
_LEXEMES = re.compile(rb'[^"\\\s{}\[\],:]+|["\\]|[\s{}\[\],:]+')


class _VerifiedReader:
    """Bound reads and lexical token size before the incremental parser sees them."""

    def __init__(self, stream: BinaryIO, expected_size: int) -> None:
        self.stream = stream
        self.expected_size = expected_size
        self.count = 0
        self.digest = hashlib.sha256()
        self.in_string = False
        self.escaped = False
        self.token_bytes = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise ValueError("unbounded catalog read forbidden")
        if size == 0:
            return b""
        data = self.stream.read(min(size, READ_CHUNK_BYTES))
        self.count += len(data)
        if self.count > min(MAX_RAW_BYTES, self.expected_size):
            raise ValueError("raw catalog exceeds declared length or 512 MiB hard limit")
        self.digest.update(data)
        # Bound strings (including skipped values) and number tokens across chunks.
        for match in _LEXEMES.finditer(data):
            token = match.group()
            if self.in_string:
                self.token_bytes += len(token)
                if self.token_bytes > MAX_TOKEN_BYTES:
                    raise ValueError("catalog scalar exceeds token limit")
                if self.escaped:
                    self.escaped = False
                elif token == b"\\":
                    self.escaped = True
                elif token == b'"':
                    self.in_string = False
                    self.token_bytes = 0
            elif token == b'"':
                self.in_string = True
                self.token_bytes = 0
            elif token[:1] in b" \t\r\n{}[],:":
                self.token_bytes = 0
            else:
                self.token_bytes += len(token)
                if self.token_bytes > MAX_TOKEN_BYTES:
                    raise ValueError("catalog scalar exceeds token limit")
        return data


@dataclass
class _Frame:
    path: tuple[str | int, ...]
    kind: str
    captured: bool
    value: Any = None
    key: str | None = None
    index: int = 0
    keys: set[str] = field(default_factory=set)
    key_bytes: int = 0


def _selected_envelope(reader: _VerifiedReader, skus: set[str]) -> dict[str, Any]:
    try:
        ijson = importlib.import_module("ijson")
    except ImportError as exc:
        raise ValueError("ijson>=3.4,<4 must be installed; no whole-file fallback") from exc
    envelope: dict[str, Any] = {"products": {}, "terms": {"OnDemand": {}}}
    stack: list[_Frame] = []
    active_keys = active_key_bytes = selected_bytes = 0
    root_seen = False
    required_maps = {(), ("products",), ("terms",), ("terms", "OnDemand")}
    seen_maps: set[tuple[str | int, ...]] = set()
    try:
        for event, value in ijson.basic_parse(reader, buf_size=READ_CHUNK_BYTES):
            if event == "map_key":
                frame = stack[-1]
                if value in frame.keys:
                    raise ValueError("duplicate JSON key in raw catalog")
                size = len(value.encode("utf-8"))
                active_keys += 1
                active_key_bytes += size
                if active_keys > MAX_ACTIVE_KEYS or active_key_bytes > MAX_ACTIVE_KEY_BYTES:
                    raise ValueError("catalog key bookkeeping limit exceeded")
                frame.keys.add(value)
                frame.key_bytes += size
                frame.key = value
                if frame.captured:
                    selected_bytes += len(json.dumps(value)) + 1
                if selected_bytes > MAX_SELECTED_BYTES:
                    raise ValueError("selected envelope exceeds bounded size")
                continue
            if event in {"end_map", "end_array"}:
                frame = stack.pop()
                active_keys -= len(frame.keys)
                active_key_bytes -= frame.key_bytes
                continue
            if not stack:
                if root_seen or event != "start_map":
                    raise ValueError("exactly one catalog root object required")
                root_seen = True
                path: tuple[str | int, ...] = ()
                parent = None
            else:
                parent = stack[-1]
                if parent.kind == "start_map":
                    if parent.key is None:
                        raise ValueError("missing object key")
                    path = (*parent.path, parent.key)
                    parent.key = None
                else:
                    path = (*parent.path, parent.index)
                    parent.index += 1
            if path in required_maps:
                if event != "start_map":
                    raise ValueError("catalog structural object missing")
                seen_maps.add(path)
            metadata = len(path) == 1 and path[0] in _METADATA
            product = len(path) == 2 and path[0] == "products" and path[1] in skus
            terms = len(path) == 3 and path[:2] == ("terms", "OnDemand") and path[2] in skus
            capture = product or terms or (parent is not None and parent.captured)
            if metadata and event != "string":
                raise ValueError("catalog metadata must be strings")
            if (product or terms) and event != "start_map":
                raise ValueError("selected product/OnDemand terms must be objects")
            container = event in {"start_map", "start_array"}
            if capture or metadata:
                if event == "number":
                    raise ValueError("selected AWS fields must use explicit decimal strings")
                selected_bytes += 2 if container else len(json.dumps(value)) + 1
                if selected_bytes > MAX_SELECTED_BYTES:
                    raise ValueError("selected envelope exceeds bounded size")
                obj: Any = ({} if event == "start_map" else []) if container else value
                if metadata:
                    metadata_key = path[0]
                    assert isinstance(metadata_key, str)
                    envelope[metadata_key] = obj
                elif product:
                    envelope["products"][path[1]] = obj
                elif terms:
                    envelope["terms"]["OnDemand"][path[2]] = obj
                elif parent is not None:
                    if parent.kind == "start_map":
                        parent.value[path[-1]] = obj
                    else:
                        parent.value.append(obj)
            else:
                obj = None
            if container:
                if len(stack) >= MAX_DEPTH:
                    raise ValueError("catalog nesting limit exceeded")
                stack.append(_Frame(path, event, capture, obj))
    except ijson.JSONError as exc:
        raise ValueError("invalid or truncated catalog JSON") from exc
    if stack or seen_maps != required_maps or not root_seen:
        raise ValueError("incomplete catalog structure")
    return envelope


def inspect_large_ec2_catalog(
    raw_path: Path,
    *,
    entry: SourceRegistryEntry,
    manifest: dict[str, Any],
    selections: list[CatalogSelection],
    as_of: datetime,
    max_age_days: int,
) -> dict[str, Any]:
    """Select exact SKUs without fetching, snapshot creation or business DB writes.

    ``manifest`` must come from the caller's trusted SnapshotStore, not the raw
    payload. A derived in-memory manifest is used only to reuse the small-catalog
    validator. It is never persisted or represented as a new official snapshot.
    Unsupported regions/services and unapproved registries fail closed.
    """
    if entry.product_code != "ec2":
        raise ValueError("only authorized public us-east-1 EC2 catalogs are supported")
    validate_official_catalog_source(entry)
    if not 1 <= len(selections) <= 100 or len({s.sku for s in selections}) != len(selections):
        raise ValueError("one to 100 unique exact SKUs required")
    expected_size = manifest.get("content_length_bytes")
    expected_hash = manifest.get("content_sha256")
    if (
        type(expected_size) is not int
        or not 0 < expected_size <= MAX_RAW_BYTES
        or not isinstance(expected_hash, str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected_hash)
    ):
        raise ValueError("trusted raw SHA256 and positive length within 512 MiB required")
    with raw_path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
            raise ValueError("raw snapshot must be a regular file with declared byte count")
        reader = _VerifiedReader(stream, expected_size)
        envelope = _selected_envelope(reader, {s.sku for s in selections})
        # Exhaustion is mandatory even when every requested SKU was found early.
        if reader.read(1) or reader.count != expected_size:
            raise ValueError("raw snapshot byte count mismatch")
        if reader.digest.hexdigest() != expected_hash:
            raise ValueError("raw snapshot SHA256 mismatch")
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("raw snapshot changed during inspection")
    selected_raw = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(selected_raw) > MAX_SELECTED_BYTES:
        raise ValueError("selected envelope exceeds bounded size")
    selected_hash = hashlib.sha256(selected_raw).hexdigest()
    derived_manifest = {
        **manifest,
        "content_sha256": selected_hash,
        "content_length_bytes": len(selected_raw),
    }
    result = inspect_official_catalog(
        selected_raw,
        entry=entry,
        manifest=derived_manifest,
        selections=selections,
        as_of=as_of,
        max_age_days=max_age_days,
    )
    result.update(
        rule_version=RULE_VERSION,
        selected_validator_rule_version=result["rule_version"],
        raw_sha256=expected_hash,
        raw_content_length_bytes=expected_size,
        original_snapshot_integrity_verified=True,
        full_catalog_semantically_validated=False,
        validation_scope="selected_skus_complete_ondemand_terms_only",
        selected_skus=sorted(s.sku for s in selections),
        selected_envelope=envelope,
        selected_envelope_sha256=selected_hash,
        selected_envelope_content_length_bytes=len(selected_raw),
        selected_envelope_is_official_snapshot=False,
        fetching_performed=False,
    )
    return result
