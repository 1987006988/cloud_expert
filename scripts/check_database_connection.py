import argparse
import json
from typing import Any

import _bootstrap  # noqa: F401
from sqlalchemy import create_engine, text

from cloud_expert.config.settings import get_settings, resolve_database_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SQLAlchemy database connectivity.")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    database_url = (
        resolve_database_url(args.database_url)
        if args.database_url
        else get_settings().database_url
    )
    result = check_database_connection(database_url)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result["valid"] else 1


def check_database_connection(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    result: dict[str, Any] = {
        "database_url": _redact_database_url(database_url),
        "valid": False,
        "select_1": False,
        "transaction_commit": False,
        "transaction_rollback": False,
    }
    try:
        with engine.connect() as connection:
            result["dialect"] = engine.dialect.name
            result["pool_status"] = _pool_status(engine)
            result["select_1"] = connection.execute(text("select 1")).scalar_one() == 1
            result.update(_connection_identity(connection))
            result.update(_check_transactions(connection))
        result["valid"] = (
            result["select_1"] and result["transaction_commit"] and result["transaction_rollback"]
        )
    finally:
        engine.dispose()
    return result


def _connection_identity(connection: Any) -> dict[str, Any]:
    dialect = connection.engine.dialect.name
    if dialect == "postgresql":
        row = (
            connection.execute(
                text(
                    """
                select
                  version() as server_version,
                  current_database() as current_database,
                  current_user as current_user,
                  current_schema() as current_schema,
                  current_setting('TimeZone') as timezone
                """
                )
            )
            .mappings()
            .one()
        )
        return dict(row)
    row = connection.execute(text("select sqlite_version() as server_version")).mappings().one()
    return {
        "server_version": row["server_version"],
        "current_database": None,
        "current_user": None,
        "current_schema": None,
        "timezone": None,
    }


def _check_transactions(connection: Any) -> dict[str, bool]:
    temporary_table_sql = (
        "create temporary table r011_connection_check (value integer) on commit preserve rows"
        if connection.engine.dialect.name == "postgresql"
        else "create temporary table r011_connection_check (value integer)"
    )
    connection.execute(text(temporary_table_sql))
    connection.commit()

    commit_transaction = connection.begin()
    connection.execute(text("insert into r011_connection_check (value) values (1)"))
    commit_transaction.commit()
    committed_count = connection.execute(
        text("select count(*) from r011_connection_check where value = 1")
    ).scalar_one()
    connection.commit()

    rollback_transaction = connection.begin()
    connection.execute(text("insert into r011_connection_check (value) values (2)"))
    rollback_transaction.rollback()
    rolled_back_count = connection.execute(
        text("select count(*) from r011_connection_check where value = 2")
    ).scalar_one()
    connection.commit()

    return {
        "transaction_commit": committed_count == 1,
        "transaction_rollback": rolled_back_count == 0,
    }


def _pool_status(engine: Any) -> str:
    status = getattr(engine.pool, "status", None)
    if callable(status):
        return str(status())
    return str(engine.pool.__class__.__name__)


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    prefix, suffix = database_url.split("://", 1)
    credentials, host = suffix.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{prefix}://{username}:***@{host}"


if __name__ == "__main__":
    raise SystemExit(main())
