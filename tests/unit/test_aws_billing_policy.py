"""Synthetic HTML/database fixtures only, never real-source approval."""

from datetime import timedelta

import pytest

from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import aws_billing_policy as policies
from tests.unit.test_official_catalog import NOW, fixture

HTML = """<html><p>SYNTHETIC TEST ONLY</p>
<p>除非另行说明，否则我们的价格不包含适用的税费和关税（包括增值税和适用的销售税）。</p>
<p>Amazon S3 的存储使用量以二进制 (GB) 计算，其中 1GB 等于 2<sup>30</sup> 字节。这种测量单位也称为 Gibibyte (GiB)。</p>
<p>您需要为 S3 存储桶中的存储对象支付费用。费率取决于对象大小、一个月期间存储对象的时间和 S3 Standard。</p>
<p>S3 请求费用取决于请求类型，按请求数量计费，PUT 和 GET。</p>
<p>定价按每个实例从启动到终止或停止使用的时间计算，以小时为单位。Linux。</p></html>"""


def provider(session):
    row = Provider(
        code="aws", name="SYNTHETIC AWS", display_name="Synthetic only", provider_type="fixture"
    )
    session.add(row)
    session.flush()
    return row


def policy_entry(product="s3"):
    entry, _, _ = fixture("AmazonS3" if product == "s3" else "AmazonEC2")
    return entry.model_copy(
        update={
            "source_id": policies.POLICY_SOURCES[product],
            "url": f"https://aws.amazon.com/{policies.POLICY_PATHS[product]}",
            "expected_content_type": ["text/html"],
            "domain_policy": entry.domain_policy.model_copy(
                update={
                    "allowed_domains": ["aws.amazon.com"],
                    "allow_redirects": True,
                    "allowed_redirect_domains": ["aws.amazon.com"],
                }
            ),
        }
    )


def store_snapshot(session, root, entry, raw, owner, *, final_url=None):
    captured = NOW - timedelta(hours=12)
    stored = SnapshotStore(root).store(
        entry=entry,
        requested_url=entry.url,
        final_url=final_url or entry.url,
        http_status=200,
        content_type=entry.expected_content_type[0],
        content=raw,
        response_headers={},
        content_metadata={"synthetic": True},
        fetch_duration_ms=0,
        captured_at=captured,
    )
    manifest = stored.manifest
    document = SourceDocument(
        provider_id=owner.id,
        source_type="pricing",
        title="SYNTHETIC ONLY",
        url=final_url or entry.url,
        cloud_partition="aws",
        authority_level="official_primary",
        captured_at=captured,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        mime_type=manifest.content_type,
        http_status=200,
        is_current=True,
    )
    session.add(document)
    session.flush()
    snapshot = SnapshotRecord(
        source_document_id=document.id,
        source_id=entry.source_id,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        manifest_path=str(stored.manifest_path.relative_to(root)),
        content_type=manifest.content_type,
        content_length_bytes=len(raw),
        captured_at=captured,
        change_status="first_seen",
        is_current=True,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


@pytest.fixture
def policy_fixture(session, tmp_path, monkeypatch):
    entry = policy_entry()
    row = store_snapshot(
        session,
        tmp_path,
        entry,
        HTML.encode(),
        provider(session),
        final_url="https://aws.amazon.com/cn/s3/pricing/",
    )
    monkeypatch.setattr(policies, "get_entry_by_source_id", lambda _: entry)
    session.commit()
    return row, entry, tmp_path


def test_language_redirect_is_international_and_gib_is_not_decimal_gb(session, policy_fixture):
    snapshot, _, root = policy_fixture
    plan = policies.prepare_billing_policy(
        session, snapshot.id, product_code="s3", raw_root=root, as_of=NOW
    )
    assert len(plan["records"]) == 4
    assert plan["tax_status"] == "tax_excluded" and plan["tax_rate"] is None
    assert plan["customer_payable_tax"] == "unknown" and not plan["customer_eligible"]
    for row in plan["records"]:
        assert row["raw_sha256"] == snapshot.content_hash
        assert '"cloud_partition":"aws"' in row["excerpt"]
    assert '"canonical_unit":"GiB"' in plan["records"][1]["excerpt"]
    assert policies.evidence_row(session, plan["records"][0]) is None
    assert not session.new and not session.dirty


@pytest.mark.parametrize(
    "old,new",
    [
        ("不包含适用的税费", "包含适用的税费"),
        ("<sup>30</sup>", "30"),
        ("<sup>30</sup>", "<sup>10</sup>"),
        ("二进制", "十进制"),
        ("一个月期间存储对象的时间", "某段时间"),
        ("按请求数量计费", "计费未知"),
    ],
)
def test_missing_or_changed_policy_never_defaults_to_zero_or_decimal_gb(old, new):
    with pytest.raises(ValueError, match="policy clause"):
        policies.extract_policy_clauses("s3", HTML.replace(old, new))


@pytest.mark.parametrize(
    "mutation",
    ["hash", "partition", "old", "stale", "url", "source", "manifest", "path", "robots", "terms"],
)
def test_policy_provenance_fails_closed(session, policy_fixture, monkeypatch, mutation):
    row, entry, root = policy_fixture
    if mutation == "hash":
        (root / row.storage_path).write_bytes(b"x" * row.content_length_bytes)
    elif mutation == "partition":
        row.source_document.cloud_partition = "aws_cn"
    elif mutation == "old":
        row.is_current = False
    elif mutation == "stale":
        row.captured_at = NOW - timedelta(days=30)
    elif mutation == "url":
        row.source_document.url = "https://www.amazonaws.cn/s3/pricing/"
    elif mutation == "source":
        row.source_id = "unregistered"
    elif mutation == "manifest":
        (root / row.manifest_path).write_text("{}")
    elif mutation == "path":
        row.manifest_path = "../outside.json"
    elif mutation == "robots":
        entry = entry.model_copy(update={"robots_allowed": None})
    else:
        entry = entry.model_copy(update={"terms_review_status": "pending_review"})
    monkeypatch.setattr(policies, "get_entry_by_source_id", lambda _: entry)
    session.commit()
    with pytest.raises(ValueError):
        policies.prepare_billing_policy(
            session, row.id, product_code="s3", raw_root=root, as_of=NOW
        )


def test_policy_evidence_idempotence_conflict_and_rollback(session, policy_fixture):
    snapshot, _, root = policy_fixture
    plan = policies.prepare_billing_policy(
        session, snapshot.id, product_code="s3", raw_root=root, as_of=NOW
    )
    row = plan["records"][0]
    proof = policies.evidence_row(session, row, apply=True)
    assert proof.review_status == "machine_extracted"
    assert policies.evidence_row(session, row, apply=True).id == proof.id
    session.rollback()
    assert policies.evidence_row(session, row) is None
    proof = policies.evidence_row(session, row, apply=True)
    proof.excerpt = "tampered"
    session.commit()
    with pytest.raises(ValueError, match="evidence conflict"):
        policies.evidence_row(session, row)


def test_ec2_requires_its_own_hour_and_tax_policy():
    clauses = policies.extract_policy_clauses("ec2", HTML)
    assert [row["kind"] for row in clauses] == ["tax", "compute_unit"]
    with pytest.raises(ValueError):
        policies.extract_policy_clauses("ec2", HTML.replace("以小时为单位", "时间未知"))
    with pytest.raises(ValueError):
        policies.extract_policy_clauses("other", HTML)
