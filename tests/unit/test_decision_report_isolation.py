from unittest.mock import MagicMock, Mock

from cloud_expert.decision import reporting


def test_explicit_report_directory_does_not_overwrite_global_review_sample(monkeypatch, tmp_path):
    payload = {
        "valid": True,
        "run_code": "synthetic",
        "scenario_code": "synthetic",
        "scenario_version": "v1",
        "policy_version": "v1",
        "candidate_results": 0,
        "eligible": 0,
        "blocked": 0,
        "requires_review": 0,
        "dimension_status_counts": {},
        "confidence_counts": {},
        "customer_eligible": 0,
        "sensitivity_status": "not_applicable",
        "review_counts": {},
        "internal_only": 0,
    }
    monkeypatch.setattr(reporting, "decision_report_payload", lambda *a: payload)
    monkeypatch.setattr(reporting, "result_rows", lambda *a: [])
    sample = Mock()
    monkeypatch.setattr(reporting, "write_review_sample", sample)
    session = MagicMock()
    result = reporting.write_decision_reports(session, "synthetic", report_dir=tmp_path)
    assert result == payload
    sample.assert_called_once_with(session, "synthetic", tmp_path / "review_sample.csv")
    assert (tmp_path / "decision_result_rows.json").read_text(encoding="utf-8") == "[]"
