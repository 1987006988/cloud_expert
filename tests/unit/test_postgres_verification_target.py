import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./test_outputs/business.sqlite",
        "postgresql://localhost/business",
        "postgresql://remote.example/cloud_expert_r011_test",
        "postgresql://localhost/cloud_expert_r011_test?host=remote.example",
    ],
)
def test_reject_nonisolated_postgres_target(monkeypatch, url):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    module = importlib.import_module("run_postgres_verification")
    with pytest.raises(ValueError):
        module.validate_test_target(url)


def test_accept_named_local_isolation_only(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    module = importlib.import_module("run_postgres_verification")
    module.validate_test_target("postgresql://127.0.0.1/cloud_expert_r011_synthetic")
