import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.postgres


def test_model_review_queue_jsonb_constraints_and_rollback() -> None:
    url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required")
    if not url.startswith("postgresql") or "_r011_" not in url:
        pytest.fail("Use an isolated PostgreSQL R011 test database")
    engine = create_engine(url, future=True)
    try:
        columns = {
            column["name"]: str(column["type"]).upper()
            for column in inspect(engine).get_columns("model_review_assignment")
        }
        assert columns["evidence_ids"] == "JSONB"
        audit_columns = {
            column["name"]: str(column["type"]).upper()
            for column in inspect(engine).get_columns("model_review_audit_event")
        }
        assert audit_columns["affected_records"] == "JSONB"
        code = f"synthetic-week14-{uuid4().hex}"
        with engine.connect() as connection:
            outer = connection.begin()
            run_id = connection.scalar(
                text(
                    "INSERT INTO model_review_run "
                    "(run_code, policy_version, reviewer_model, input_fingerprint, "
                    "reviewed_at, summary_json) VALUES "
                    "(:code, 'test', 'deterministic_evidence_precheck', :hash, now(), '{}'::json) "
                    "RETURNING id"
                ),
                {"code": code, "hash": "a" * 64},
            )
            finding_id = connection.scalar(
                text(
                    "INSERT INTO model_review_finding "
                    "(run_id, subject_type, subject_id, verdict, reason_code, rationale, "
                    "evidence_ids, input_hash) VALUES "
                    "(:run_id, 'synthetic', 1, 'requires_source_verification', 'test', "
                    "'Synthetic fixture', '[]'::json, :hash) RETURNING id"
                ),
                {"run_id": run_id, "hash": "b" * 64},
            )
            assignment_id = connection.scalar(
                text(
                    "INSERT INTO model_review_assignment "
                    "(precheck_run_id, precheck_finding_id, target_type, target_id, input_hash, "
                    "review_state, evidence_ids) VALUES "
                    "(:run_id, :finding_id, 'synthetic', 1, :hash, "
                    "'pending_model_review', '[1]'::jsonb) RETURNING id"
                ),
                {"run_id": run_id, "finding_id": finding_id, "hash": "b" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO model_review_audit_event "
                    "(assignment_id, event_code, new_status, source, reason, "
                    "affected_records, downstream_rebuild_required, timestamp) VALUES "
                    "(:assignment_id, 'created', 'pending_model_review', 'test', 'synthetic', "
                    "'[]'::jsonb, false, now())"
                ),
                {"assignment_id": assignment_id},
            )
            duplicate = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO model_review_assignment "
                        "(precheck_run_id, precheck_finding_id, target_type, target_id, "
                        "input_hash, review_state, evidence_ids) VALUES "
                        "(:run_id, :finding_id, 'synthetic', 1, :hash, "
                        "'pending_model_review', '[]'::jsonb)"
                    ),
                    {"run_id": run_id, "finding_id": finding_id, "hash": "b" * 64},
                )
            duplicate.rollback()
            invalid = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "UPDATE model_review_assignment SET review_state='human_approved' "
                        "WHERE id=:assignment_id"
                    ),
                    {"assignment_id": assignment_id},
                )
            invalid.rollback()
            outer.rollback()
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM model_review_run WHERE run_code=:code"),
                    {"code": code},
                )
                == 0
            )
    finally:
        engine.dispose()
