# Remaining Risks

Generated at: 2026-07-22T23:02:12+08:00

`R011_STATUS=COMPLETED`

`WEEK7_GATE=NO-GO`

## R011 Residual Notes

- The Compose service currently relies on Compose-managed storage rather than
  an explicitly named volume in `docker-compose.yml`.
- Compose local test credentials are static test credentials. They are not
  production credentials and must not be reused outside local validation.
- Models use PostgreSQL `JSON`, not `JSONB`; this is now documented and tested
  as JSON behavior only.
- Repository-level retry semantics are not implemented. R011 validates the
  database uniqueness boundary and rollback behavior.

## Still Open Outside R011

- `R005_expand_canonical_schema_to_prompt`
- `R006_field_matrix_required_columns`
- `R007_strengthen_comparability_assessment`
- `R008_review_queue_policy`
- `R009_raise_test_coverage`

R009 remains open because total project coverage is still 79%, below the 85%
gate. Do not start Week 7 product mapping until Stage 2 is closed or explicitly
waived.
