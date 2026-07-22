import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context
from cloud_expert.database import models  # noqa: F401
from cloud_expert.database.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_database_url(url: str) -> str:
    if url == "sqlite:///:memory:":
        return url
    if url.startswith("sqlite:///"):
        sqlite_path = url.removeprefix("sqlite:///")
        if sqlite_path.startswith("/") or (len(sqlite_path) >= 2 and sqlite_path[1] == ":"):
            return url
        return f"sqlite:///{(PROJECT_ROOT / sqlite_path).as_posix()}"
    return url


def run_migrations_offline() -> None:
    url = _resolve_database_url(os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url")))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_database_url(
        os.getenv("DATABASE_URL", configuration["sqlalchemy.url"])
    )
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
