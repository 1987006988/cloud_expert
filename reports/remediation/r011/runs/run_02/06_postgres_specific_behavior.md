# PostgreSQL-Specific Behavior

Generated at: 2026-07-22T23:02:12+08:00

Validated by `tests/integration/test_postgres_r011.py`.

## Enum-Like Values

Status: passed.

The current schema does not use native PostgreSQL enum types. It uses
`VARCHAR` columns plus check constraints generated from stable Python enums.

Validated:

- legal enum-like values insert successfully
- invalid `market_mode` is rejected by PostgreSQL
- check constraints are present in schema inspection
- native PostgreSQL enum inventory is empty and stable across re-upgrade

## Numeric And Decimal

Status: passed.

Validated:

- `PriceSnapshot.unit_price` is returned as `Decimal`
- `NUMERIC(24, 8)` persists scale and rounds `0.123456789` to `0.12345679`
- `maximum_quantity` rounds `9.999999999` to `10.00000000`
- `NormalizedSpecification.quality_score` uses bounded numeric precision

## JSON And JSONB

Status: passed with documented difference.

The current SQLAlchemy models use generic `JSON`, not PostgreSQL `JSONB`.
Schema inspection confirmed `metadata_json` columns render as `JSON`.

Validated:

- nested JSON object writes and reads
- empty object writes and reads
- JSON `null` value writes and reads

No JSONB index or JSONB operator behavior is claimed for R011.

## Foreign Keys

Status: passed.

Validated:

- invalid `Evidence.source_document_id` is rejected
- deleting a referenced `Product` is rejected
- Evidence and Snapshot chains are not silently lost through product deletion
- `NormalizedSpecification` references must point to existing source/product
  entities

## Unique Constraints

Status: passed.

Validated:

- duplicate `Provider.code` is rejected
- duplicate `SnapshotRecord(source_id, content_hash)` is rejected
- concurrent duplicate provider creation yields one committed row and one
  unique-conflict rollback
- schema inspection confirms key unique constraints for provider, product,
  region, snapshot, normalized specification, and related tables

## Timezone

Status: passed with an ORM limitation documented.

Validated:

- PostgreSQL server timezone is `Etc/UTC`
- UTC-aware Python datetimes can be written and read through the ORM
- retrieved datetimes are timezone-aware for PostgreSQL in the integration test

Schema inspection renders PostgreSQL timestamp columns as `TIMESTAMP`; this is
SQLAlchemy inspector display behavior. The migration/model declarations use
`DateTime(timezone=True)`.

## Transaction Rollback

Status: passed.

Validated:

- an exception in a multi-row Provider -> SourceDocument -> Snapshot transaction
  rolls back the entire batch
- no partial provider, source document, or snapshot rows remain after rollback

## Concurrency And Idempotency Boundary

Status: passed.

Validated:

- two concurrent workers attempting the same `Provider.code` result in exactly
  one committed insert and one unique-conflict rollback
- no duplicate provider row remains

The current repositories do not implement automatic retry logic; R011 validates
the database boundary and transaction rollback behavior, not a retry service.
