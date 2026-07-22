from pathlib import Path

from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_downgrade_reupgrade() -> None:
    db_path = Path("migration_test.sqlite")
    db_path.unlink(missing_ok=True)
    url = f"sqlite:///{db_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)

    upgrade(config, "head")
    engine = create_engine(url, future=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "provider",
        "product",
        "evidence",
        "price_snapshot",
        "product_mapping",
        "canonical_field_definition",
        "normalization_rule",
        "normalization_run",
        "normalized_specification",
        "comparability_assessment",
    } <= tables
    assert inspector.get_unique_constraints("provider")
    assert inspector.get_check_constraints("price_snapshot")

    downgrade(config, "base")
    with engine.connect() as connection:
        remaining_tables = connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT IN ('sqlite_sequence', 'alembic_version')"
            )
        ).all()
    assert remaining_tables == []

    upgrade(config, "head")
    inspector = inspect(engine)
    assert "provider" in inspector.get_table_names()
    engine.dispose()
    db_path.unlink(missing_ok=True)
