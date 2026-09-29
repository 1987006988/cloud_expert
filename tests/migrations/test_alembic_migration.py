from pathlib import Path

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


@pytest.fixture(autouse=True)
def _isolate_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_alembic_upgrade_downgrade_reupgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "migration_test.sqlite"
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


def test_model_review_audit_blocks_downgrade_with_recorded_run(tmp_path: Path) -> None:
    db_path = tmp_path / "model_review_migration_test.sqlite"
    url = f"sqlite:///{db_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    upgrade(config, "head")

    engine = create_engine(url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO model_review_run "
                "(run_code, policy_version, reviewer_model, input_fingerprint, reviewed_at, summary_json) "
                "VALUES (:run_code, :policy_version, :reviewer_model, :input_fingerprint, "
                ":reviewed_at, :summary_json)"
            ),
            {
                "run_code": "test-audit-run",
                "policy_version": "test",
                "reviewer_model": "test",
                "input_fingerprint": "test",
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "summary_json": "{}",
            },
        )

    downgrade(config, "0012_week11_model_review_audit")
    with pytest.raises(RuntimeError, match="recorded runs"):
        downgrade(config, "-1")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0012_week11_model_review_audit"
        )
        assert connection.scalar(text("SELECT COUNT(*) FROM model_review_run")) == 1
    engine.dispose()


def test_week14_assignment_blocks_downgrade_without_losing_history(tmp_path: Path) -> None:
    db_path = tmp_path / "week14_review_migration_test.sqlite"
    url = f"sqlite:///{db_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    upgrade(config, "head")

    engine = create_engine(url, future=True)
    with engine.begin() as connection:
        run_id = connection.execute(
            text(
                "INSERT INTO model_review_run "
                "(run_code, policy_version, reviewer_model, input_fingerprint, reviewed_at, summary_json) "
                "VALUES ('week14-test', 'test', 'deterministic_evidence_precheck', "
                ":hash, '2026-01-01T00:00:00+00:00', '{}') RETURNING id"
            ),
            {"hash": "a" * 64},
        ).scalar_one()
        finding_id = connection.execute(
            text(
                "INSERT INTO model_review_finding "
                "(run_id, subject_type, subject_id, verdict, reason_code, rationale, "
                "evidence_ids, input_hash) VALUES "
                "(:run_id, 'synthetic', 1, 'requires_dual_model_review', 'test', "
                "'Synthetic test', '[]', :hash) RETURNING id"
            ),
            {"run_id": run_id, "hash": "b" * 64},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO model_review_assignment "
                "(precheck_run_id, precheck_finding_id, target_type, target_id, input_hash, "
                "review_state, evidence_ids) VALUES "
                "(:run_id, :finding_id, 'synthetic', 1, :hash, 'pending_model_review', '[]')"
            ),
            {"run_id": run_id, "finding_id": finding_id, "hash": "b" * 64},
        )

    with pytest.raises(RuntimeError, match="nonempty model_review_assignment"):
        downgrade(config, "-1")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0014_week14_review_workflow"
        )
        assert connection.scalar(text("SELECT count(*) FROM model_review_assignment")) == 1
    engine.dispose()
