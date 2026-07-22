import argparse
import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from cloud_expert.config.settings import get_settings, resolve_database_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect database schema fingerprint.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    database_url = (
        resolve_database_url(args.database_url)
        if args.database_url
        else get_settings().database_url
    )
    engine = create_engine(database_url, future=True)
    try:
        result = inspect_schema(engine, database_url)
    finally:
        engine.dispose()

    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if not args.quiet:
        print(payload)
    return 0


def inspect_schema(engine: Engine, database_url: str) -> dict[str, Any]:
    inspector = inspect(engine)
    tables: dict[str, Any] = {}
    for table_name in sorted(inspector.get_table_names()):
        tables[table_name] = {
            "columns": [
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": column["nullable"],
                    "default": column.get("default"),
                    "primary_key": bool(column.get("primary_key")),
                }
                for column in inspector.get_columns(table_name)
            ],
            "primary_key": inspector.get_pk_constraint(table_name),
            "foreign_keys": inspector.get_foreign_keys(table_name),
            "unique_constraints": inspector.get_unique_constraints(table_name),
            "check_constraints": inspector.get_check_constraints(table_name),
            "indexes": inspector.get_indexes(table_name),
        }
    return {
        "database_url": _redact_database_url(database_url),
        "dialect": engine.dialect.name,
        "alembic_versions": _read_alembic_versions(engine),
        "postgres_enums": _read_postgres_enums(engine)
        if engine.dialect.name == "postgresql"
        else [],
        "tables": tables,
    }


def _read_alembic_versions(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        names = inspect(connection).get_table_names()
        if "alembic_version" not in names:
            return []
        rows = connection.execute(text("select version_num from alembic_version")).scalars()
        return [str(row) for row in rows]


def _read_postgres_enums(engine: Engine) -> list[dict[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                select typ.typname as enum_name, enum.enumlabel as enum_value
                from pg_type typ
                join pg_enum enum on typ.oid = enum.enumtypid
                join pg_namespace ns on ns.oid = typ.typnamespace
                where ns.nspname not in ('pg_catalog', 'information_schema')
                order by typ.typname, enum.enumsortorder
                """
            )
        ).mappings()
        return [
            {
                "enum_name": str(row["enum_name"]),
                "enum_value": str(row["enum_value"]),
            }
            for row in rows
        ]


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    prefix, suffix = database_url.split("://", 1)
    credentials, host = suffix.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{prefix}://{username}:***@{host}"


if __name__ == "__main__":
    raise SystemExit(main())
