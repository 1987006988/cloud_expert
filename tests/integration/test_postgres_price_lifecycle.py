"""Real PostgreSQL transaction/locking behavior; all price facts are synthetic."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from cloud_expert.database.base import Base
from tests.unit.test_price_lifecycle import (
    Verifier,
    _apply,
    _audit_counts,
    _history,
    _plan,
    _resolve,
    _seed,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def isolated_pricing_engine():
    value = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not value:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required")
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or not (url.database or "").startswith("cloud_expert_r011_")
        or url.host not in {"localhost", "127.0.0.1"}
    ):
        pytest.fail("Use an isolated local PostgreSQL R011 test database")
    schema = "synthetic_price_lifecycle_" + uuid4().hex
    base = create_engine(url)
    engine = base.execution_options(schema_translate_map={None: schema})
    created = False
    try:
        with base.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        Base.metadata.create_all(engine)
        yield engine
    finally:
        # Only this test's UUID-named schema in the verified isolated database.
        if created:
            with base.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        base.dispose()


def test_postgres_price_replacement_atomic_rollback_and_idempotence(
    isolated_pricing_engine, tmp_path
):
    with Session(isolated_pricing_engine) as session:
        data = _seed(session, tmp_path)
        verifier = Verifier(data)
        history = _history(session)
        plan = _plan(session, data, verifier)
        assert _apply(session, plan, verifier, apply=True).created
        assert _audit_counts(session) == (1, 2, 2, 2)
        session.rollback()
        assert _audit_counts(session) == (0, 0, 0, 0)
        assert _history(session) == history
        first = _apply(session, plan, verifier, apply=True)
        session.commit()
        repeated = _apply(session, plan, verifier, apply=True)
        session.commit()
        assert not repeated.created
        assert first.receipt_sha256 == repeated.receipt_sha256
        assert _audit_counts(session) == (1, 2, 2, 2)
        assert _history(session) == history
        for old, new in zip(*data["groups"][:2], strict=True):
            result = _resolve(session, old, verifier)
            assert result.status == "superseded" and result.current_price_id == new


def test_postgres_conflicting_connection_locks_then_retries_idempotently(
    isolated_pricing_engine, tmp_path
):
    with Session(isolated_pricing_engine) as first, Session(isolated_pricing_engine) as second:
        data = _seed(first, tmp_path)
        verifier = Verifier(data)
        first_plan = _plan(first, data, verifier)
        second_plan = _plan(second, data, verifier)
        _apply(first, first_plan, verifier, apply=True)
        second.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError):
            _apply(second, second_plan, verifier, apply=True)
        second.rollback()
        first.commit()
        retried = _apply(second, second_plan, verifier, apply=True)
        second.commit()
        assert not retried.created
        assert _audit_counts(second) == (1, 2, 2, 2)
