# Remaining Risks

Stage 1 verdict: **PARTIAL COMPLETE**.

`WEEK7_GATE=NO-GO`

- `R011_postgresql_migration_validation`: open. Docker daemon was unavailable,
  so live PostgreSQL upgrade/downgrade/re-upgrade was not executed.
- `R009_raise_test_coverage`: open. Coverage is 79%, below the 85% gate.
- `R005_expand_canonical_schema_to_prompt`: open. Canonical schema expansion is
  outside Stage 1.
- `R006_field_matrix_required_columns`: open. Matrix expansion is outside
  Stage 1.
- `R007_strengthen_comparability_assessment`: open. Readiness logic is still not
  blocker-aware enough for customer-facing claims.
- `R008_review_queue_policy`: open. Review queues remain visible and must not be
  treated as reviewed truth.
- Week 6 comparability assessments remain readiness records only. They are not
  product mappings, pricing guidance, scores, or sales claims.

Next execution order:

1. Start Docker Desktop and close PostgreSQL validation.
2. Run fresh migration, downgrade, re-upgrade, and PostgreSQL integration
   checks for enum, numeric, foreign key, unique constraint, and timezone
   behavior.
3. Proceed to Stage 2 for Canonical schema/enums, qualifier and scope rules,
   ComparabilityAssessment logic, Field Matrix status columns, coverage uplift,
   and ReviewItem governance.
4. Reopen Week 7 gate review only after those items are complete or explicitly
   waived.
