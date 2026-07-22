import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from cloud_expert.config.settings import get_settings

REQUIRED_TABLES = {
    "provider",
    "product",
    "source_document",
    "snapshot_record",
    "evidence",
    "product_specification",
    "normalization_run",
    "normalized_specification",
}


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    try:
        result = validate_default_database(settings.database_url)
    finally:
        engine.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


def validate_default_database(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            versions = (
                [
                    str(row)
                    for row in connection.execute(
                        text("select version_num from alembic_version")
                    ).scalars()
                ]
                if "alembic_version" in tables
                else []
            )
    finally:
        engine.dispose()

    head = _current_head()
    missing_tables = sorted(REQUIRED_TABLES - tables)
    stale_revisions = [revision for revision in versions if revision != head]
    result: dict[str, Any] = {
        "database_url": _redact_database_url(database_url),
        "database_path": _sqlite_path(database_url),
        "head": head,
        "alembic_versions": versions,
        "missing_required_tables": missing_tables,
        "stale_revisions": stale_revisions,
    }
    result["valid"] = versions == [head] and not missing_tables and not stale_revisions
    return result


def _current_head() -> str:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    return str(script.get_current_head())


def _sqlite_path(database_url: str) -> str | None:
    if not database_url.startswith("sqlite:///") or database_url == "sqlite:///:memory:":
        return None
    return str(Path(database_url.removeprefix("sqlite:///")).resolve())


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    prefix, suffix = database_url.split("://", 1)
    credentials, host = suffix.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{prefix}://{username}:***@{host}"


if __name__ == "__main__":
    raise SystemExit(main())
