# Ingestion Runbook

## Validate Registry

```bash
.\.venv312\Scripts\python scripts\validate_source_registry.py
```

Expected result for the Week 2 fixtures:

```text
total_sources: 3
valid_sources: 3
errors: 0
```

## Fetch One Source

```bash
.\.venv312\Scripts\python scripts\ingest_source.py --source-id synthetic_html_fixture
```

The first run should create a raw snapshot and database records. A second run
with the same fixture content should return `unchanged`.

## Fetch Filtered Sources

```bash
.\.venv312\Scripts\python scripts\ingest_source.py --provider synthetic_provider --enabled-only
.\.venv312\Scripts\python scripts\ingest_source.py --market-mode domestic
.\.venv312\Scripts\python scripts\ingest_source.py --dry-run
```

The Week 2 CLI caps concurrency at a small value and does not run browser
automation.

## Inspect History

```bash
.\.venv312\Scripts\python scripts\show_source_history.py --source-id synthetic_html_fixture
```

## Compare Versions

```bash
.\.venv312\Scripts\python scripts\compare_source_versions.py --source-id synthetic_html_fixture --latest
```

If only one snapshot exists, the command exits successfully with
`change_status=unknown` and explains that two snapshots are required.

## Validate Raw Snapshots

```bash
.\.venv312\Scripts\python scripts\validate_raw_snapshots.py
```

## Troubleshooting

- `blocked` with `domain_not_allowed`: check URL, domain policy, redirects, and
  SSRF protections.
- `blocked` with `requires_authentication` or `requires_browser`: the source is
  out of scope for the Week 2 HTTP fetcher.
- `failed` with `mime_mismatch`: update the registry only if the official source
  truly returns that content type.
- `failed` with `file_too_large`: increase the per-source limit only after
  review.
- Empty history usually means the source has not been fetched into the selected
  `CLOUD_EXPERT_RAW_DATA_DIR`.

