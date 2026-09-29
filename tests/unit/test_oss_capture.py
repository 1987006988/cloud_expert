"""Synthetic-only evidence planning tests; no business database or vendor prices."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from cloud_expert.database.models.pricing import PriceSKU, PriceSnapshot
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import Evidence, SourceDocument
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import oss_capture as oss
from cloud_expert.pricing.oss_capture import (
    FRAME_URL,
    HEADERS,
    HEADING,
    MAX_BYTES,
    REGISTRY_URL,
    SOURCE_ID,
    plan_oss_capture,
    read_oss_capture,
)

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def fixture() -> tuple[SourceRegistryEntry, dict[str, Any]]:
    entry = SourceRegistryEntry.model_validate(
        {
            "source_id": SOURCE_ID,
            "provider_code": "aliyun",
            "product_code": "oss",
            "market_mode": "domestic",
            "cloud_partition": "aliyun_public_cn",
            "source_type": "pricing",
            "authority_level": "official_primary",
            "title": "SYNTHETIC OSS TEST",
            "url": REGISTRY_URL,
            "expected_content_type": ["text/html"],
            "domain_policy": {"allowed_domains": ["www.aliyun.com"]},
            "enabled": False,
            "requires_browser": True,
            "manual_only": True,
            "allow_automated_fetch": False,
            "automated_fetch_allowed": False,
            "terms_review_status": "approved",
            "reviewed_at": NOW,
        }
    )
    bundle = {
        "capture_kind": "selected_visible_dom_excerpt",
        "page_url": REGISTRY_URL + "/ossbag",
        "frame_url": FRAME_URL,
        "captured_at": "2026-09-29T18:00:00.123Z",
        "section_heading": HEADING,
        "section_locator": f"div.des-title.line-title.des-mb20:has-text({HEADING})",
        "scope_text": "SYNTHETIC ONLY. 中国内地地域包括：华北 2（北京）。按量付费方式下，各地域统一价格。",
        "rows": [
            HEADERS.copy(),
            ["存储费用", "数据存储（本地冗余存储）"] + ["987.654 元/GB/月"] * 5,
        ],
        "unit_text": "SYNTHETIC ONLY. 阿里云 OSS 的存储容量和流量是以二进制 (GB) 计算，其中 1 GB 等于 2^30 字节。这种测量单位也称为 Gibibyte (GiB)。同样的，1 TB 等于 2^40 字节，即 1024 GB。",
        "discount_section": [],
    }
    return entry, bundle


def plan(entry: SourceRegistryEntry, bundle: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(bundle, ensure_ascii=False).encode()
    return plan_oss_capture(
        raw, entry=entry, expected_sha256=hashlib.sha256(raw).hexdigest(), as_of=NOW
    )


def test_plan_is_stable_evidence_only_and_original_time_preserved() -> None:
    entry, bundle = fixture()
    before = copy.deepcopy(bundle)
    first = plan(entry, bundle)
    assert first == plan(entry, bundle)
    assert bundle == before
    assert first["snapshot_candidate"]["captured_at"] == bundle["captured_at"]
    assert first["snapshot_candidate"]["http_status"] is None
    assert first["snapshot_candidate"]["full_dom_available"] is False
    assert first["snapshot_candidate"]["wire_response_bytes_available"] is False
    assert first["unit_evidence"]["bytes_per_unit"] == 2**30
    assert first["scope"]["region_selected_in_ui"] is False
    assert first["unresolved_semantics"]["tariff_timezone"] == "unknown"
    assert first["unresolved_semantics"]["month_basis"] == "unknown"
    assert not first["promotion_allowed"] and not first["database_write_performed"]
    assert first["price_skus_created"] == first["price_snapshots_created"] == 0
    ids = [e["idempotency_key"] for e in first["evidence_candidates"]]
    assert len(ids) == len(set(ids)) == 5
    for evidence in first["evidence_candidates"]:
        assert evidence["content_hash"] == hashlib.sha256(evidence["excerpt"].encode()).hexdigest()
    bundle["rows"][1][2] = "888.123 元/GB/月"
    assert plan(entry, bundle)["snapshot_idempotency_key"] != first["snapshot_idempotency_key"]


def test_discount_and_free_grants_never_merge_into_prices() -> None:
    entry, bundle = fixture()
    bundle["discount_section"] = [
        "【公共云】中国内地地域官网折扣价-- 价格详情\nSYNTHETIC 中国内地地域包括：华北 2（北京）。目录价基础上叠加一定折扣。888.123 元/GB/月"
    ]
    bundle["rows"].append(["请求费用", "PUT 类型请求"] + ["每月每地域免费额度：SYNTHETIC ONLY"] * 5)
    result = plan(entry, bundle)
    assert result["evidence_candidates"][-1]["price_basis"] == "public_discount_separate_unapproved"
    assert result["evidence_candidates"][-2]["price_basis"] == "public_list_visible_row"
    assert result["unresolved_semantics"]["free_grant_eligibility_and_aggregation"] == "unknown"


@pytest.mark.parametrize(
    "change",
    [
        {"page_url": "https://evil.invalid/price/product#/oss/detail"},
        {"page_url": REGISTRY_URL + "?account=private"},
        {"frame_url": FRAME_URL + "?account=private"},
        {"capture_kind": "full_html"},
        {"section_locator": "table"},
        {"section_heading": "【金融云】中国内地地域"},
        {"scope_text": "中国内地地域包括：华北 2（北京）及国际。按量付费方式下，各地域统一价格。"},
        {"unit_text": "1 GB = 1000000000 bytes"},
        {"captured_at": "2026-09-29T18:00:00"},
        {"captured_at": "2099-01-01T00:00:00Z"},
        {"request_headers": {"Authorization": "secret"}},
    ],
)
def test_rejects_unbound_capture_scope_or_extra_fields(change: dict[str, Any]) -> None:
    entry, bundle = fixture()
    bundle.update(change)
    with pytest.raises(ValueError):
        plan(entry, bundle)


@pytest.mark.parametrize(
    "mutation", ["width", "header", "duplicate", "inheritance", "sensitive", "too_many"]
)
def test_row_header_and_sensitive_guards(mutation: str) -> None:
    entry, bundle = fixture()
    if mutation == "width":
        bundle["rows"][1].pop()
    elif mutation == "header":
        bundle["rows"][0][2], bundle["rows"][0][3] = bundle["rows"][0][3], bundle["rows"][0][2]
    elif mutation == "duplicate":
        bundle["rows"].append(bundle["rows"][1].copy())
    elif mutation == "inheritance":
        bundle["rows"][1][0] = "-"
    elif mutation == "sensitive":
        bundle["rows"][1][2] = "Authorization: Bearer synthetic-private-data"
    else:
        bundle["rows"] += bundle["rows"][1:] * 9
    with pytest.raises(ValueError):
        plan(entry, bundle)


@pytest.mark.parametrize(
    "change",
    [
        {"automated_fetch_allowed": True},
        {"allow_automated_fetch": True},
        {"manual_only": False},
        {"enabled": True},
        {"terms_review_status": "pending"},
        {"reviewed_at": None},
        {"robots_allowed": False},
        {"cloud_partition": "aliyun_public_intl"},
    ],
)
def test_registry_cannot_be_broadened(change: dict[str, Any]) -> None:
    entry, bundle = fixture()
    with pytest.raises(ValueError):
        plan(entry.model_copy(update=change), bundle)


def test_hash_size_duplicate_json_and_timestamp_guards() -> None:
    entry, bundle = fixture()
    raw = json.dumps(bundle).encode()
    with pytest.raises(ValueError, match="SHA256"):
        plan_oss_capture(raw, entry=entry, expected_sha256="0" * 64, as_of=NOW)
    for data in (b"x" * (MAX_BYTES + 1), b'{"capture_kind":1,"capture_kind":2}'):
        with pytest.raises(ValueError):
            plan_oss_capture(
                data, entry=entry, expected_sha256=hashlib.sha256(data).hexdigest(), as_of=NOW
            )
    with pytest.raises(ValueError, match="aware"):
        plan_oss_capture(
            raw,
            entry=entry,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            as_of=NOW.replace(tzinfo=None),
        )


def test_bounded_reader(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    path.write_bytes(b"x" * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="oversized"):
        read_oss_capture(path)


def test_cli_dry_run_and_immutable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import import_oss_browser_capture as cli

    entry, bundle = fixture()
    raw = json.dumps(bundle).encode()
    capture = tmp_path / "capture.json"
    capture.write_bytes(raw)
    report = tmp_path / "plan.json"
    monkeypatch.setattr(cli, "get_entry_by_source_id", lambda _: entry)
    argv = [
        "import_oss_browser_capture.py",
        str(capture),
        "--expected-sha256",
        hashlib.sha256(raw).hexdigest(),
        "--as-of",
        NOW.isoformat(),
        "--report",
        str(report),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    first = report.read_bytes()
    assert json.loads(capsys.readouterr().out)["mode"] == "dry_run"
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    assert report.read_bytes() == first and capture.read_bytes() == raw
    monkeypatch.setattr(sys, "argv", argv + ["--apply"])
    with pytest.raises(SystemExit):
        cli.main()


def full_fixture() -> tuple[SourceRegistryEntry, dict[str, Any]]:
    entry, bundle = fixture()
    bundle["rows"] = [HEADERS.copy()] + [
        [category, label] + ["987.654 SYNTHETIC ONLY"] * 5
        for label, category in oss.ROW_CATEGORIES.items()
    ]
    bundle["discount_section"] = [
        oss.DISCOUNT_HEADING
        + "\n中国内地地域包括：华北 2（北京）。目录价基础上叠加一定折扣。SYNTHETIC ONLY"
    ]
    return entry, bundle


def capture_file(
    tmp_path: Path, entry: SourceRegistryEntry, bundle: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    raw = json.dumps(bundle, ensure_ascii=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / f"synthetic_{digest[:12]}.json"
    path.write_bytes(raw)
    return path, oss.plan_oss_capture(raw, entry=entry, expected_sha256=digest, as_of=NOW)


def apply_isolated(
    engine: Engine, path: Path, prior: dict[str, Any], store: SnapshotStore
) -> dict[str, Any]:
    with Session(engine) as session:
        return oss.apply_oss_capture(
            session,
            path,
            expected_sha256=prior["snapshot_candidate"]["content_sha256"],
            previous_plan_sha256=prior["plan_sha256"],
            as_of=NOW,
            store=store,
        )


def test_apply_all_13_idempotent_original_capture_no_prices(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, bundle = full_fixture()
    monkeypatch.setattr(oss, "get_entry_by_source_id", lambda _: entry)
    path, prior = capture_file(tmp_path, entry, bundle)
    store = SnapshotStore(tmp_path / "raw")
    first = apply_isolated(engine, path, prior, store)
    pointer = store.latest_pointer_path(entry).read_bytes()
    second = apply_isolated(engine, path, prior, store)
    assert first["snapshot_created"] and len(first["evidence_created_ids"]) == 13
    assert not second["snapshot_created"] and second["evidence_created_ids"] == []
    assert first["evidence_ids"] == second["evidence_existing_ids"]
    assert not second["database_write_performed"]
    assert store.latest_pointer_path(entry).read_bytes() == pointer
    with Session(engine) as session:
        snapshot = session.get(SnapshotRecord, first["snapshot_record_id"])
        assert snapshot is not None
        assert snapshot.source_document.http_status is None
        assert snapshot.source_document.captured_at == datetime.fromisoformat(
            bundle["captured_at"]
        ).replace(tzinfo=None)
        assert (store.raw_data_dir / snapshot.storage_path).read_bytes() == path.read_bytes()
        manifest = store.load_manifest(store.raw_data_dir / snapshot.manifest_path)
        assert manifest.http_status == 0
        assert manifest.content_metadata["capture_kind"] == "selected_visible_dom_excerpt"
        assert manifest.content_metadata["full_html_available"] is False
        assert manifest.content_metadata["wire_response_bytes_available"] is False
        assert manifest.content_metadata["original_captured_at"] == bundle["captured_at"]
        assert session.scalar(select(func.count()).select_from(Evidence)) == 13
        assert session.scalar(select(func.count()).select_from(PriceSKU)) == 0
        assert session.scalar(select(func.count()).select_from(PriceSnapshot)) == 0
        assert all(e.evidence_type == "json_path" for e in session.scalars(select(Evidence)))


@pytest.mark.parametrize(
    "mutation", ["raw", "valid_registry_change", "registry_disallowed", "wrong_plan"]
)
def test_apply_revalidates_current_raw_registry_and_plan(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    entry, bundle = full_fixture()
    path, prior = capture_file(tmp_path, entry, bundle)
    if mutation == "raw":
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "valid_registry_change":
        entry = entry.model_copy(update={"title": "Changed after dry run"})
    elif mutation == "registry_disallowed":
        entry = entry.model_copy(update={"terms_review_status": "disallowed"})
    else:
        prior["plan_sha256"] = "0" * 64
    monkeypatch.setattr(oss, "get_entry_by_source_id", lambda _: entry)
    store = SnapshotStore(tmp_path / "raw")
    with pytest.raises(ValueError):
        apply_isolated(engine, path, prior, store)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 0
        assert session.scalar(select(func.count()).select_from(SnapshotRecord)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 0
    assert not store.latest_pointer_path(entry).exists()


def test_evidence_failure_rolls_back_fetcher_commit_and_can_retry(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, bundle = full_fixture()
    path, prior = capture_file(tmp_path, entry, bundle)
    monkeypatch.setattr(oss, "get_entry_by_source_id", lambda _: entry)
    store = SnapshotStore(tmp_path / "raw")
    original = oss._get_or_create_evidence
    calls = 0

    def failing(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ValueError("synthetic failure after snapshot and several Evidence inserts")
        return original(*args, **kwargs)

    monkeypatch.setattr(oss, "_get_or_create_evidence", failing)
    with pytest.raises(ValueError, match="synthetic failure"):
        apply_isolated(engine, path, prior, store)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 0
        assert session.scalar(select(func.count()).select_from(SnapshotRecord)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 0
    assert not store.latest_pointer_path(entry).exists()
    assert len(list(store.raw_data_dir.rglob("manifest.json"))) == 1
    monkeypatch.setattr(oss, "_get_or_create_evidence", original)
    result = apply_isolated(engine, path, prior, store)
    assert len(result["evidence_ids"]) == 13
    assert len(list(store.raw_data_dir.rglob("manifest.json"))) == 1
    assert store.latest_pointer_path(entry).exists()


def test_history_preserved_and_old_reimport_never_becomes_current(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, bundle = full_fixture()
    monkeypatch.setattr(oss, "get_entry_by_source_id", lambda _: entry)
    path1, plan1 = capture_file(tmp_path, entry, bundle)
    store = SnapshotStore(tmp_path / "raw")
    first = apply_isolated(engine, path1, plan1, store)
    bundle["captured_at"] = "2026-09-29T19:00:00Z"
    path2, plan2 = capture_file(tmp_path, entry, bundle)
    second = apply_isolated(engine, path2, plan2, store)
    pointer = store.latest_pointer_path(entry).read_bytes()
    replay = apply_isolated(engine, path1, plan1, store)
    assert not replay["snapshot_is_current"]
    assert replay["evidence_ids"] == first["evidence_ids"]
    assert store.latest_pointer_path(entry).read_bytes() == pointer
    with Session(engine) as session:
        one = session.get(SnapshotRecord, first["snapshot_record_id"])
        two = session.get(SnapshotRecord, second["snapshot_record_id"])
        assert one is not None and two is not None
        assert not one.is_current and not one.source_document.is_current
        assert two.is_current and two.previous_snapshot_id == one.id
        assert session.scalar(select(func.count()).select_from(Evidence)) == 26
    bundle["captured_at"] = "2026-09-29T18:30:00Z"
    older, prior = capture_file(tmp_path, entry, bundle)
    with pytest.raises(ValueError, match="older"):
        apply_isolated(engine, older, prior, store)


def test_failed_new_version_restores_previous_db_current_flags_and_pointer(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, bundle = full_fixture()
    monkeypatch.setattr(oss, "get_entry_by_source_id", lambda _: entry)
    path1, plan1 = capture_file(tmp_path, entry, bundle)
    store = SnapshotStore(tmp_path / "raw")
    first = apply_isolated(engine, path1, plan1, store)
    pointer_before = store.latest_pointer_path(entry).read_bytes()
    bundle["captured_at"] = "2026-09-29T19:00:00Z"
    path2, plan2 = capture_file(tmp_path, entry, bundle)

    def fail_after_legacy_commit(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("after legacy commit before evidence")

    monkeypatch.setattr(oss, "_get_or_create_evidence", fail_after_legacy_commit)
    with pytest.raises(ValueError, match="after legacy commit"):
        apply_isolated(engine, path2, plan2, store)
    assert store.latest_pointer_path(entry).read_bytes() == pointer_before
    assert len(list(store.raw_data_dir.rglob("manifest.json"))) == 2
    with Session(engine) as session:
        original = session.get(SnapshotRecord, first["snapshot_record_id"])
        assert original is not None and original.is_current
        assert original.source_document.is_current
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1
        assert session.scalar(select(func.count()).select_from(SnapshotRecord)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 13


@pytest.mark.parametrize("mutation", ["retained_raw", "evidence_excerpt", "evidence_lineage"])
def test_existing_immutable_corruption_fails_closed(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    entry, bundle = full_fixture()
    monkeypatch.setattr(oss, "get_entry_by_source_id", lambda _: entry)
    path, prior = capture_file(tmp_path, entry, bundle)
    store = SnapshotStore(tmp_path / "raw")
    first = apply_isolated(engine, path, prior, store)
    with Session(engine) as session:
        snapshot = session.get(SnapshotRecord, first["snapshot_record_id"])
        evidence = session.get(Evidence, first["evidence_ids"][0])
        assert snapshot is not None and evidence is not None
        if mutation == "retained_raw":
            (store.raw_data_dir / snapshot.storage_path).write_bytes(b"tampered synthetic raw")
        elif mutation == "evidence_excerpt":
            evidence.excerpt = "tampered synthetic evidence"
        else:
            evidence.evidence_type = "html_section"
        session.commit()
    with pytest.raises(ValueError):
        apply_isolated(engine, path, prior, store)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 13


def test_cli_apply_requires_new_report_dir_and_commits_isolated_db_only(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import import_oss_browser_capture as cli

    entry, bundle = full_fixture()
    path, prior = capture_file(tmp_path, entry, bundle)
    monkeypatch.setattr(oss, "get_entry_by_source_id", lambda _: entry)
    monkeypatch.setattr(cli, "get_entry_by_source_id", lambda _: entry)
    store = SnapshotStore(tmp_path / "raw")
    monkeypatch.setattr(
        cli, "_apply_to_env", lambda args, as_of: apply_isolated(engine, path, prior, store)
    )
    report_dir = tmp_path / "run_01"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_oss_browser_capture.py",
            str(path),
            "--expected-sha256",
            prior["snapshot_candidate"]["content_sha256"],
            "--as-of",
            NOW.isoformat(),
            "--apply",
            "--previous-plan-sha256",
            prior["plan_sha256"],
            "--report-dir",
            str(report_dir),
        ],
    )
    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["evidence_ids"]) == 13
    before = (report_dir / "result.json").read_bytes()
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)["database_commit_completed"] is False
    assert (report_dir / "result.json").read_bytes() == before
