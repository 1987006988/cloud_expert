import importlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def importer(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("import_aws_document_policy")


def _session():
    return SimpleNamespace(new=[], dirty=[], deleted=[])


def _plan():
    return {
        "records": [{"snapshot_record_id": 7, "kind": "general_tax_exclusion", "scope": "general"}]
    }


def test_plan_sorted_stable_and_read_only(monkeypatch, importer):
    builder = Mock(return_value=_plan())
    monkeypatch.setattr(importer, "prepare_document_policy", builder)
    now = datetime.now(UTC)
    first = importer.prepare(_session(), [2, 1], Path("raw"), now)
    second = importer.prepare(_session(), [1, 2], Path("raw"), now)
    assert first == second
    assert [call.args[1] for call in builder.call_args_list[:2]] == [1, 2]


@pytest.mark.parametrize("ids", [[], [1, 1]])
def test_plan_rejects_ambiguous_ids(ids, importer):
    with pytest.raises(ValueError):
        importer.prepare(_session(), ids, Path("raw"), datetime.now(UTC))


def test_apply_hash_mismatch_writes_nothing(monkeypatch, importer):
    monkeypatch.setattr(importer, "prepare_document_policy", Mock(return_value=_plan()))
    writer = Mock()
    monkeypatch.setattr(importer, "evidence_row", writer)
    with pytest.raises(ValueError, match="fresh plan"):
        importer.apply_plan(_session(), [1], Path("raw"), datetime.now(UTC), "0" * 64)
    writer.assert_not_called()


@pytest.mark.parametrize("exists", [False, True])
def test_apply_tracks_idempotence_without_approval(monkeypatch, exists, importer):
    monkeypatch.setattr(importer, "prepare_document_policy", Mock(return_value=_plan()))
    row = SimpleNamespace(id=19, content_hash="a" * 64)
    writer = Mock(side_effect=[row] if exists else [None, row])
    monkeypatch.setattr(importer, "evidence_row", writer)
    now = datetime.now(UTC)
    expected = importer.prepare(_session(), [1], Path("raw"), now)["plan_sha256"]
    result = importer.apply_plan(_session(), [1], Path("raw"), now, expected)
    assert result["created_evidence"] == int(not exists)
    assert result["existing_evidence"] == int(exists)
    assert result["bindings"][0]["evidence_id"] == 19
    assert not result["price_approval"]
    assert not result["tco_eligible"]
    assert not result["customer_eligible"]
