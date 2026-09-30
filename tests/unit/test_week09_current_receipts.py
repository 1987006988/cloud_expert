import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "valid,current,percent",
    [
        (True, True, 89.9),
        (True, False, 89.9),
        (False, True, 89.9),
        (True, True, 84.9),
        (True, True, None),
    ],
)
def test_gate_uses_current_receipts_not_old_pass_flags(monkeypatch, valid, current, percent):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    module = importlib.import_module("check_week09_gate")
    monkeypatch.setattr(
        module,
        "read_gate_receipts",
        lambda *args, **kwargs: {
            "coverage": {
                "valid": valid,
                "current_code_verified": current,
                "metrics": {"coverage_percent": percent},
            },
            "postgres": {"valid": valid, "current_code_verified": current, "metrics": {}},
        },
    )
    coverage, postgres = module._verification_gates()
    expected = valid and current and percent is not None and percent >= 85
    assert coverage["passed"] is expected
    assert postgres["passed"] is (valid and current)


def test_missing_receipts_does_not_fall_back_to_historical_reports(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    module = importlib.import_module("check_week09_gate")
    monkeypatch.setenv("CLOUD_EXPERT_GATE_RECEIPTS", str(tmp_path / "absent.yaml"))
    coverage, postgres = module._verification_gates()
    assert not coverage["passed"]
    assert not postgres["passed"]
