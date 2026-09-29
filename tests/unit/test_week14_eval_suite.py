from cloud_expert.evals.suite import build_suite, run_suite


def test_synthetic_eval_suite_has_unique_cases_and_no_critical_failures() -> None:
    cases = build_suite()
    assert len(cases) >= 25
    assert len({case.case_code for case in cases}) == len(cases)
    result = run_suite()
    assert result["critical_failures"] == []
    assert result["passed"] == result["case_count"]
    assert result["full_chain_coverage"] is False
