# Raw Data Storage

## Directory Layout

Raw snapshots are stored below `CLOUD_EXPERT_RAW_DATA_DIR`, defaulting to
`data/raw`.

```text
data/raw/{market_mode}/{provider_code}/{product_code}/{source_id}/{yyyy}/{mm}/{timestamp}_{hash8}/
```

`product_code` uses `unscoped` when the registry entry is not product-specific.
Path segments are sanitized and all write paths are checked to remain inside the
raw data root.

## Snapshot Files

Each snapshot directory contains:

- `raw.bin`: exact fetched response bytes.
- `content.html`, `content.json`, or `content.pdf`: content-type-specific copy
  for easier inspection.
- `metadata.json`: parsed metadata such as HTML title, JSON type, or PDF page
  count.
- `response_headers.json`: sanitized response headers only.
- `change_report.json`: comparison against the previous stored version.
- `manifest.json`: canonical machine-readable snapshot manifest.

The latest pointer for each source is stored at:

```text
data/raw/{market_mode}/{provider_code}/{product_code}/{source_id}/latest.json
```

## Manifest Guarantees

The manifest records:

- `snapshot_id`, source identity, requested URL, final URL, capture timestamp.
- HTTP status, content type, content length, raw SHA-256 hash, normalized hash,
  and normalization version.
- Relative storage paths for raw content, headers, metadata, and change report.
- Previous snapshot id, change status, duplicate flag, collector version, and
  extracted metadata.

Snapshots are immutable. Identical content for the same `source_id` is
deduplicated and reported as unchanged instead of overwriting old files.

## Validation

Run:

```bash
.\.venv312\Scripts\python scripts\validate_raw_snapshots.py
```

The validator checks manifest readability, raw-file hash integrity, latest
pointer validity, path traversal safety, sanitized headers, and temporary file
cleanup.

