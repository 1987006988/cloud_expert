import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.postgres


def test_market_context_uses_jsonb_constraints_and_transaction_rollback() -> None:
    url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required")
    if not url.startswith("postgresql") or "_r011_" not in url:
        pytest.fail("Use an isolated PostgreSQL R011 test database")
    engine = create_engine(url, future=True)
    try:
        columns = {
            column["name"]: str(column["type"]).upper()
            for column in inspect(engine).get_columns("market_context")
        }
        assert columns["preferred_region_codes"] == "JSONB"
        assert columns["provider_partition_codes"] == "JSONB"
        assert inspect(engine).get_check_constraints("market_context")
        code = f"market-test-{uuid4().hex}"
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text(
                    "INSERT INTO market_context "
                    "(context_code, market_mode, country_code, preferred_region_codes, "
                    "provider_partition_codes, tax_context) "
                    "VALUES (:code, 'international', 'MX', '[]'::jsonb, "
                    "'[\"aws\"]'::jsonb, 'tax_unknown')"
                ),
                {"code": code},
            )
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO market_context "
                        "(context_code, market_mode, preferred_region_codes, "
                        "provider_partition_codes, tax_context) "
                        "VALUES (:code, 'invalid', '[]'::jsonb, '[]'::jsonb, 'tax_unknown')"
                    ),
                    {"code": f"{code}-invalid"},
                )
            savepoint.rollback()
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM market_context WHERE context_code=:code"),
                    {"code": code},
                )
                == 1
            )
            transaction.rollback()
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM market_context WHERE context_code=:code"),
                    {"code": code},
                )
                == 0
            )
    finally:
        engine.dispose()
