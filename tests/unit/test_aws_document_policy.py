"""Synthetic HTML and transient ORM objects only; no business database or approvals."""

import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from cloud_expert.database.models.provider import Provider
from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.database.models.source import SourceDocument
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.ingestion.storage.snapshot_store import SnapshotStore
from cloud_expert.pricing import aws_document_policy as policies
from cloud_expert.pricing.aws_billing_policy import digest

NOW = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
CAPTURED = NOW - timedelta(hours=1)
PRINCIPLES = "aws_pricing_principles"
METRICS = "aws_s3_storage_metrics_units"
USAGE = "aws_s3_billing_usage_codes"
LIFECYCLE = "aws_ec2_instance_lifecycle_billing"
SOURCES = {
    PRINCIPLES: (
        None,
        "https://docs.aws.amazon.com/whitepapers/latest/how-aws-pricing-works/key-principles.html",
        "key-principles",
        "Key principles",
    ),
    METRICS: (
        "s3",
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage_lens_metrics_glossary.html",
        "storage_lens_metrics_glossary",
        "Amazon S3 Storage Lens metrics glossary",
    ),
    USAGE: (
        "s3",
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/aws-usage-report-understand.html",
        "aws-usage-report-understand",
        "Understanding your AWS billing and usage reports for Amazon S3",
    ),
    LIFECYCLE: (
        "ec2",
        "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html",
        "ec2-instance-lifecycle",
        "Amazon EC2 instance state changes",
    ),
}

PRINCIPLES_HTML = """
<h2 id="understand-the-fundamentals-of-pricing">Fundamentals (synthetic)</h2>
<p>For compute resources, you pay by the hour or by the second from the time you
launch a resource until the time you stop or terminate it, unless you have made
a reservation for which the cost is agreed upon beforehand.</p>
<p>Except as otherwise noted, AWS prices are exclusive of applicable taxes and duties,
including value-added tax (VAT) and sales tax. For customers with a Japanese billing
address, use of AWS is subject to Japanese Consumption Tax.</p>
"""
METRICS_HTML = """
<div class="awsdocs-note"><p>The unit of measurement for S3 storage bytes is in binary
gigabytes (GB), where 1 GB is 2<sup>30</sup> bytes, 1 TB is 2<sup>40</sup> bytes,
and 1 PB is 2<sup>50</sup> bytes. This unit of measurement is also known as a
gibibyte (GiB), as defined by the International Electrotechnical Commission (IEC).</p></div>
"""
USAGE_HTML = """
<p>Amazon S3 billing and usage reports use codes and abbreviations. For usage types in
the table that follows, replace <code>region</code>, <code>region1</code>, and
<code>region2</code> with abbreviations from AWS Region billing codes.</p>
<div><p>For the US East (N. Virginia) Region, the region prefix is omitted from usage
type codes. For example, TimedStorage-ByteHrs instead of USE1-TimedStorage-ByteHrs.</p></div>
<table><thead><tr><th>Usage Type</th><th>Units</th><th>Granularity</th><th>Description</th></tr></thead>
<tbody><tr><td><code><code>region</code>-TimedStorage-ByteHrs</code></td>
<td>GB-Month</td><td>Daily</td><td>The number of GB-months that data was stored in
S3 Standard storage</td></tr>
<tr><td><code><code>region</code>-Requests-Tier1</code></td><td>Count</td><td>Hourly</td>
<td>The number of <code>PUT</code>, <code>COPY</code>, or <code>POST</code> requests for
S3 Standard, RRS, and tags, plus <code>LIST</code> requests for all buckets and objects</td></tr>
<tr><td><code><code>region</code>-Requests-Tier2</code></td><td>Count</td><td>Hourly</td>
<td>The number of <code>GET</code> and all other non-Tier1 requests</td></tr></tbody></table>
"""
LIFECYCLE_HTML = """
<h2 id="instance-billing-by-state">Billing by instance state</h2>
<p>The following table provides a brief description of each instance state and indicates
whether instance usage is billed. Some AWS resources, such as Amazon EBS volumes and
Elastic IP addresses, incur charges regardless of the instance's state.</p>
<table><tr><th>Instance state</th><th>Description</th><th>Instance usage billing</th></tr>
<tr><td>running</td><td>The instance is running and ready for use.</td><td>Billed</td></tr>
<tr><td>stopping</td><td>Preparing to stop (synthetic).</td><td>Not billed
<p>If you hibernate an instance, you're billed while the instance is in the stopping state.</p></td></tr>
<tr><td>terminated</td><td>Deleted (synthetic).</td><td>Not billed
<p>Reserved Instances that applied to terminated instances are billed until the end of
their term according to their payment option.</p></td></tr></table>
<h2 id="instance-launch">Pending instances</h2>
<p>As soon as your instance transitions to the <code>running</code> state, you're billed
for each second, with a one-minute minimum, that you keep the instance running, even if
the instance remains idle and you don't connect to it.</p>
<h2 id="instance-stop-start">Stopped instances</h2>
<p>Each time you transition an instance from <code>stopped</code> to <code>running</code>,
you are charged per second when the instance is running, with a minimum of one minute per
instance start.</p>
"""
FRAGMENTS = {
    PRINCIPLES: PRINCIPLES_HTML,
    METRICS: METRICS_HTML,
    USAGE: USAGE_HTML,
    LIFECYCLE: LIFECYCLE_HTML,
}


def html(source_id: str, fragment: str | None = None) -> str:
    _, _, heading_id, heading = SOURCES[source_id]
    return (
        '<html><body><div id="main-col-body">'
        f'<h1 id="{heading_id}">{heading}</h1><p>SYNTHETIC TEST ONLY</p>'
        f"{FRAGMENTS[source_id] if fragment is None else fragment}</div></body></html>"
    )


@dataclass
class Bundle:
    session: MagicMock
    snapshot: SnapshotRecord
    entry: SourceRegistryEntry
    root: Path

    def plan(self, **kwargs: Any) -> dict[str, Any]:
        return policies.prepare_document_policy(
            cast(Session, self.session),
            self.snapshot.id,
            raw_root=self.root,
            as_of=NOW,
            **kwargs,
        )

    def manifest(self, **updates: Any) -> None:
        path = self.root / self.snapshot.manifest_path
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(updates)
        path.write_text(json.dumps(value), encoding="utf-8")


def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_id: str = METRICS) -> Bundle:
    product, url, _, _ = SOURCES[source_id]
    entry = SourceRegistryEntry.model_validate(
        {
            "source_id": source_id,
            "provider_code": "aws",
            "market_mode": "international",
            "cloud_partition": "aws",
            "product_code": product,
            "source_type": "documentation",
            "title": "SYNTHETIC DOCUMENT",
            "authority_level": "official_primary",
            "url": url,
            "expected_content_type": ["text/html"],
            "expected_encoding": "utf-8",
            "domain_policy": {"allowed_domains": ["docs.aws.amazon.com"], "allow_redirects": False},
            "reviewed_at": NOW - timedelta(days=1),
            "robots_checked_at": NOW - timedelta(days=1),
            "robots_allowed": True,
            "terms_review_status": "approved",
            "automated_fetch_allowed": True,
            "compliance_notes": "SYNTHETIC docs.aws.amazon.com CC-BY-SA-4.0 approval only.",
            "notes": "SYNTHETIC ONLY; no real facts approved.",
        }
    )
    raw = html(source_id).encode()
    stored = SnapshotStore(tmp_path).store(
        entry=entry,
        requested_url=url,
        final_url=url,
        http_status=200,
        content_type="text/html",
        content=raw,
        response_headers={},
        content_metadata={"synthetic": True},
        fetch_duration_ms=0,
        captured_at=CAPTURED,
    )
    manifest = stored.manifest
    owner = Provider(
        id=99, code="aws", name="SYNTHETIC", display_name="Synthetic", provider_type="fixture"
    )
    document = SourceDocument(
        id=900,
        provider_id=99,
        provider=owner,
        source_type="documentation",
        title=entry.title,
        url=url,
        cloud_partition="aws",
        authority_level="official_primary",
        captured_at=CAPTURED,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        mime_type="text/html",
        http_status=200,
        is_current=True,
    )
    snapshot = SnapshotRecord(
        id=901,
        source_document_id=900,
        source_document=document,
        source_id=source_id,
        content_hash=manifest.content_sha256,
        storage_path=manifest.storage_path,
        manifest_path=str(stored.manifest_path.relative_to(tmp_path)),
        content_type="text/html",
        content_length_bytes=len(raw),
        captured_at=CAPTURED,
        change_status="first_seen",
        is_current=True,
    )
    session = MagicMock(spec=Session)
    session.get.return_value = snapshot
    session.no_autoflush = nullcontext()
    fixture = Bundle(session, snapshot, entry, tmp_path)
    monkeypatch.setattr(policies, "get_entry_by_source_id", lambda _: fixture.entry)
    return fixture


@pytest.mark.parametrize(
    "source_id,count", [(PRINCIPLES, 2), (METRICS, 1), (USAGE, 3), (LIFECYCLE, 1)]
)
def test_verified_readonly_evidence_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_id: str,
    count: int,
) -> None:
    fixture = bundle(tmp_path, monkeypatch, source_id)
    plan = fixture.plan()
    assert plan == fixture.plan()
    assert len(plan["records"]) == count
    assert plan["scope"] == "internal_reference_only" and plan["review_required"] is True
    assert not any(
        plan[k]
        for k in (
            "price_approval",
            "tco_eligible",
            "customer_eligible",
            "billing_conversion_authorized",
        )
    )
    soup = BeautifulSoup(html(source_id), "html.parser")
    for record in plan["records"]:
        payload = json.loads(record["excerpt"])
        assert record["content_hash"] == digest(record["excerpt"])
        assert record["raw_sha256"] == fixture.snapshot.content_hash
        assert record["source_id"] == source_id
        assert record["source_document_id"] == 900 and record["snapshot_record_id"] == 901
        assert record["parser_rule"] == policies.RULE and record["evidence_type"] == "html_section"
        assert payload["verification_status"] == "snapshot_verified_review_required"
        assert payload["license"]["identifier"] == "CC-BY-SA-4.0"
        assert payload["license"]["source_url"] == SOURCES[source_id][1]
        assert payload["license"]["scope_notes"] == fixture.entry.notes
        assert payload["limitation"] and payload["context"]
        assert (
            str(soup.select_one(record["locator"].removeprefix("css:"))) == payload["clause_html"]
        )
        for part in payload["context"]:
            assert str(soup.select_one(part["locator"].removeprefix("css:"))) == part["html"]
    fixture.session.get.assert_called_with(SnapshotRecord, 901)
    for method in ("add", "add_all", "flush", "commit", "execute", "delete"):
        getattr(fixture.session, method).assert_not_called()


def test_general_null_product_is_scoped_not_a_tax_calculation() -> None:
    tax, compute = policies.extract_document_policy_clauses(PRINCIPLES, html(PRINCIPLES))
    assert tax["product_code"] is None
    assert tax["policy"]["tax_status"] == "tax_excluded_except_as_otherwise_noted"
    assert tax["policy"]["tax_rate"] is None
    assert tax["policy"]["customer_payable_tax"] == "unknown"
    assert "Japanese" in tax["clause"] and "Except as otherwise noted" in tax["clause"]
    assert compute["policy"] == {
        "unit_alternatives": ["hour", "second"],
        "reservation_exception": True,
    }
    assert compute["verification_status"] == "unverified_candidate"


def test_metrics_never_authorize_billing_conversion() -> None:
    row = policies.extract_document_policy_clauses(METRICS, html(METRICS))[0]
    assert row["scope"] == row["policy"]["scope"] == "storage_metrics_only"
    assert row["policy"]["bytes_per_metric_gb"] == 1_073_741_824
    assert not row["billing_conversion_authorized"]
    assert not row["policy"]["billing_conversion_authorized"]
    assert "<sup>30</sup>" in row["clause_html"]
    assert "Price unit" in row["limitation"]


@pytest.mark.parametrize(
    "replacement",
    [
        "230",
        "2 30",
        "2^30",
        "2^(30)",
        "2<sup>10</sup>",
        "10<sup>30</sup>",
        "2<sub>30</sub>",
        "2<span>30</span>",
        "2<sup>3</sup><sup>0</sup>",
        "2<sup>30.0</sup>",
        "2<sup>40</sup><sup>30</sup>",
        "2<sup>30</sup>0",
    ],
)
def test_exponents_cannot_be_inferred_from_flat_text(replacement: str) -> None:
    changed = METRICS_HTML.replace("2<sup>30</sup>", replacement)
    with pytest.raises(ValueError, match="exponent"):
        policies.extract_document_policy_clauses(METRICS, html(METRICS, changed))


def test_unrelated_correct_superscript_does_not_validate_gb() -> None:
    changed = METRICS_HTML.replace("2<sup>30</sup>", "230").replace(
        "</p>", " Note<sup>30</sup></p>"
    )
    with pytest.raises(ValueError, match="exponent"):
        policies.extract_document_policy_clauses(METRICS, html(METRICS, changed))


def test_usage_code_name_does_not_override_units_or_price_denominator() -> None:
    rows = policies.extract_document_policy_clauses(USAGE, html(USAGE))
    assert [r["policy"]["unit_label"] for r in rows] == ["GB-Month", "Count", "Count"]
    assert [r["policy"]["granularity"] for r in rows] == ["Daily", "Hourly", "Hourly"]
    assert all(r["scope"] == "billing_usage_codes_only" for r in rows)
    assert all("prefix is omitted" in r["context"][-1]["text"] for r in rows)
    assert all("request price denominator" in r["limitation"] for r in rows)


def test_lifecycle_keeps_exceptions_and_restart_minimum() -> None:
    row = policies.extract_document_policy_clauses(LIFECYCLE, html(LIFECYCLE))[0]
    assert row["policy"]["minimum_seconds_per_start"] == 60
    assert row["policy"]["idle_is_billed"] is True
    context = " ".join(c["text"] for c in row["context"])
    for qualifier in (
        "hibernate",
        "Reserved Instances",
        "Elastic IP",
        "Amazon EBS",
        "per instance start",
    ):
        assert qualifier in context


@pytest.mark.parametrize(
    "source_id,old,new",
    [
        (PRINCIPLES, "exclusive of", "inclusive of"),
        (PRINCIPLES, "Except as otherwise noted, ", ""),
        (PRINCIPLES, "Japanese Consumption Tax", "unknown tax"),
        (PRINCIPLES, "unless you have made", "even if you have made"),
        (PRINCIPLES, "understand-the-fundamentals-of-pricing", "different-section"),
        (METRICS, "binary", "decimal"),
        (METRICS, "S3 storage bytes", "S3 billing bytes"),
        (METRICS, "<sup>40</sup>", "<sup>30</sup>"),
        (USAGE, "GB-Month", "GB-Hours"),
        (USAGE, "<td>Count</td>", "<td>1000 requests</td>"),
        (USAGE, "<td>Daily</td>", "<td>Hourly</td>"),
        (USAGE, "<th>Units</th>", "<th>Price</th>"),
        (USAGE, "-Requests-Tier1", "-Tables-Requests-Tier1"),
        (USAGE, "S3 Standard storage", "all S3 storage"),
        (USAGE, "prefix is omitted", "prefix is never omitted"),
        (LIFECYCLE, "<td>Billed</td>", "<td>Not billed</td>"),
        (LIFECYCLE, "one-minute minimum", "one-hour minimum"),
        (LIFECYCLE, "minimum of one minute per", "minimum of one hour per"),
        (LIFECYCLE, "you're billed while", "you're not billed while"),
        (LIFECYCLE, "Reserved Instances that applied", "Synthetic alternate rule that applied"),
        (LIFECYCLE, "incur charges regardless", "never incur charges regardless"),
        (LIFECYCLE, 'id="instance-billing-by-state"', 'id="wrong-section"'),
        (LIFECYCLE, 'id="instance-launch"', 'id="wrong-section"'),
        (LIFECYCLE, 'id="instance-stop-start"', 'id="wrong-section"'),
    ],
)
def test_changed_clause_or_missing_qualifier_fails_closed(
    source_id: str, old: str, new: str
) -> None:
    changed = html(source_id).replace(old, new)
    assert changed != html(source_id)
    with pytest.raises(ValueError):
        policies.extract_document_policy_clauses(source_id, changed)


@pytest.mark.parametrize("source_id", list(SOURCES))
def test_duplicate_or_wrong_document_fails_closed(source_id: str) -> None:
    with pytest.raises(ValueError):
        policies.extract_document_policy_clauses(
            source_id, html(source_id, FRAGMENTS[source_id] * 2)
        )
    with pytest.raises(ValueError):
        policies.extract_document_policy_clauses(
            source_id, html(source_id).replace('id="main-col-body"', 'id="other"')
        )
    other = USAGE if source_id != USAGE else METRICS
    with pytest.raises(ValueError, match="scope"):
        policies.extract_document_policy_clauses(source_id, html(other))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "aws_s3_pricing"),
        ("product_code", None),
        ("product_code", "ec2"),
        ("source_type", "pricing"),
        ("provider_code", "other"),
        ("cloud_partition", "aws_cn"),
        ("market_mode", "domestic"),
        ("authority_level", "official_secondary"),
        ("enabled", False),
        ("terms_review_status", "unknown"),
        ("reviewed_at", None),
        ("reviewed_at", NOW),
        ("reviewed_at", CAPTURED.replace(tzinfo=None)),
        ("robots_allowed", None),
        ("robots_allowed", False),
        ("robots_checked_at", None),
        ("automated_fetch_allowed", None),
        ("allow_automated_fetch", False),
        ("manual_only", True),
        ("requires_authentication", True),
        ("requires_browser", True),
        ("fixture_response_path", "synthetic.html"),
        ("compliance_notes", None),
        ("compliance_notes", "AWS website approval is not documentation license approval"),
        ("expected_content_type", ["application/json"]),
    ],
)
def test_registry_scope_and_license_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    fixture.entry = fixture.entry.model_copy(update={field: value})
    with pytest.raises(ValueError):
        fixture.plan()


@pytest.mark.parametrize("suffix", ["?lang=en", "#unit", "/", "/../other.html"])
def test_exact_url_no_query_fragment_or_path_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    fixture.entry = fixture.entry.model_copy(update={"url": fixture.entry.url + suffix})
    with pytest.raises(ValueError, match="registry"):
        fixture.plan()


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_domains", ["aws.amazon.com"]),
        ("allow_subdomains", True),
        ("allow_redirects", True),
        ("allowed_redirect_domains", ["docs.aws.amazon.com"]),
    ],
)
def test_broadened_domain_permission_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    fixture.entry.domain_policy = fixture.entry.domain_policy.model_copy(update={field: value})
    with pytest.raises(ValueError, match="registry"):
        fixture.plan()


@pytest.mark.parametrize(
    "mutation",
    [
        "full_hash",
        "length",
        "missing_raw",
        "snapshot_old",
        "document_old",
        "stale",
        "future",
        "document_hash",
        "document_path",
        "document_mime",
        "document_http",
        "document_time",
        "document_url",
        "document_source_type",
        "document_partition",
        "provider",
        "foreign_key",
        "unknown_source",
        "manifest_escape",
        "raw_escape",
        "absolute_path",
        "manifest_missing",
        "missing_registry",
        "missing_snapshot",
    ],
)
def test_snapshot_provenance_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    row, doc = fixture.snapshot, fixture.snapshot.source_document
    raw = tmp_path / row.storage_path
    if mutation == "full_hash":
        raw.write_bytes(b"x" * row.content_length_bytes)
    elif mutation == "length":
        raw.write_bytes(raw.read_bytes() + b" ")
    elif mutation == "missing_raw":
        raw.unlink()
    elif mutation == "snapshot_old":
        row.is_current = False
    elif mutation == "document_old":
        doc.is_current = False
    elif mutation in {"stale", "future"}:
        row.captured_at = doc.captured_at = NOW + timedelta(days=1 if mutation == "future" else -15)
    elif mutation == "document_hash":
        doc.content_hash = "0" * 64
    elif mutation == "document_path":
        doc.storage_path = "different.bin"
    elif mutation == "document_mime":
        doc.mime_type = "text/plain"
    elif mutation == "document_http":
        doc.http_status = 404
    elif mutation == "document_time":
        doc.captured_at = NOW
    elif mutation == "document_url":
        doc.url = "https://aws.amazon.com/s3/pricing/"
    elif mutation == "document_source_type":
        doc.source_type = "pricing"
    elif mutation == "document_partition":
        doc.cloud_partition = "aws_cn"
    elif mutation == "provider":
        doc.provider.code = "not-aws"
    elif mutation == "foreign_key":
        row.source_document_id += 1
    elif mutation == "unknown_source":
        row.source_id = "aws_s3_pricing"
    elif mutation == "manifest_escape":
        row.manifest_path = "../outside.json"
    elif mutation == "raw_escape":
        row.storage_path = doc.storage_path = "..\\outside.bin"
        fixture.manifest(storage_path=row.storage_path)
    elif mutation == "absolute_path":
        row.manifest_path = str(tmp_path / row.manifest_path)
    elif mutation == "manifest_missing":
        (tmp_path / row.manifest_path).unlink()
    elif mutation == "missing_registry":
        monkeypatch.setattr(policies, "get_entry_by_source_id", lambda _: None)
    else:
        fixture.session.get.return_value = None
    with pytest.raises(ValueError):
        fixture.plan()


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", PRINCIPLES),
        ("product_code", "ec2"),
        ("schema_version", "2.0"),
        ("requested_url", "https://aws.amazon.com/s3/pricing/"),
        ("final_url", "https://docs.aws.amazon.com.evil.invalid/other"),
        ("source_type", "pricing"),
        ("content_sha256", "f" * 64),
        ("content_length_bytes", True),
        ("content_type", "text/plain"),
        ("http_status", 201),
        ("captured_at", "2026-09-29T23:00:00"),
        ("captured_at", NOW.isoformat()),
    ],
)
def test_manifest_binding_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    fixture.manifest(**{field: value})
    with pytest.raises(ValueError):
        fixture.plan()


def test_duplicate_manifest_keys_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    path = tmp_path / fixture.snapshot.manifest_path
    path.write_text('{"source_id":"one","source_id":"two"}', encoding="utf-8")
    with pytest.raises(ValueError):
        fixture.plan()


@pytest.mark.parametrize("age", [0, 91, True, 1.5])
def test_invalid_freshness_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, age: Any) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="freshness"):
        fixture.plan(max_age_days=age)


def test_scope_rejects_legacy_pricing_id_and_unknown() -> None:
    for source_id in ("aws_s3_pricing", "aws_ec2_pricing_on_demand", "unregistered"):
        with pytest.raises(ValueError, match="source ID"):
            policies.extract_document_policy_clauses(source_id, html(METRICS))


@pytest.mark.parametrize("field", ["product_code", "source_id", "captured_at", "content_sha256"])
def test_missing_manifest_field_including_null_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    fixture = bundle(tmp_path, monkeypatch, PRINCIPLES)
    path = tmp_path / fixture.snapshot.manifest_path
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest[field]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        fixture.plan()


def test_full_hash_covers_unselected_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    raw_path = tmp_path / fixture.snapshot.storage_path
    raw = raw_path.read_bytes()
    tampered = raw.replace(b"SYNTHETIC", b"TAMPERED!")
    assert raw != tampered and len(raw) == len(tampered)
    assert policies.extract_document_policy_clauses(METRICS, tampered.decode())
    raw_path.write_bytes(tampered)
    with pytest.raises(ValueError, match="full content hash"):
        fixture.plan()


@pytest.mark.parametrize(
    "age_days,accepted", [(0, True), (14, True), (14.01, False), (-0.01, False)]
)
def test_capture_freshness_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    age_days: float,
    accepted: bool,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    captured = NOW - timedelta(days=age_days)
    fixture.snapshot.captured_at = fixture.snapshot.source_document.captured_at = captured
    fixture.entry = fixture.entry.model_copy(
        update={
            "reviewed_at": NOW - timedelta(days=30),
            "robots_checked_at": NOW - timedelta(days=30),
        }
    )
    fixture.manifest(captured_at=captured.isoformat())
    if accepted:
        assert fixture.plan()["records"]
    else:
        with pytest.raises(ValueError):
            fixture.plan()


@pytest.mark.parametrize("snapshot_id", [0, -1, True, "901"])
def test_invalid_snapshot_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot_id: Any,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        policies.prepare_document_policy(
            cast(Session, fixture.session),
            snapshot_id,
            raw_root=tmp_path,
            as_of=NOW,
        )
    fixture.session.get.assert_not_called()


def test_naive_as_of_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="aware"):
        policies.prepare_document_policy(
            cast(Session, fixture.session),
            901,
            raw_root=tmp_path,
            as_of=NOW.replace(tzinfo=None),
        )


@pytest.mark.parametrize(
    "bad_path", ["C:\\outside.json", "C:outside.json", "\\\\host\\share\\x", "/outside.json"]
)
def test_absolute_and_network_manifest_paths_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_path: str,
) -> None:
    fixture = bundle(tmp_path, monkeypatch)
    fixture.snapshot.manifest_path = bad_path
    with pytest.raises(ValueError, match="path"):
        fixture.plan()


def test_symlink_escape_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = bundle(tmp_path / "raw", monkeypatch)
    outside = tmp_path / "outside.bin"
    outside.write_bytes((fixture.root / fixture.snapshot.storage_path).read_bytes())
    link = fixture.root / "link.bin"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("host does not permit synthetic symlink creation")
    fixture.snapshot.storage_path = fixture.snapshot.source_document.storage_path = "link.bin"
    fixture.manifest(storage_path="link.bin")
    with pytest.raises(ValueError, match="escapes raw root"):
        fixture.plan()


def test_general_document_rejects_nonnull_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = bundle(tmp_path, monkeypatch, PRINCIPLES)
    fixture.entry = fixture.entry.model_copy(update={"product_code": "ec2"})
    with pytest.raises(ValueError, match="scope"):
        fixture.plan()


def test_extraction_only_cannot_approve_and_ignores_page_footer() -> None:
    markup = html(METRICS).replace("</body>", f"<footer>{METRICS_HTML}</footer></body>")
    rows = policies.extract_document_policy_clauses(METRICS, markup)
    assert len(rows) == 1 and rows[0]["verification_status"] == "unverified_candidate"
    assert "raw_sha256" not in rows[0]
    assert not rows[0]["price_approval"]


@pytest.mark.parametrize(
    "markup", ["", "<html></html>", "x" * (2_097_152 + 1)], ids=["empty", "no-body", "oversized"]
)
def test_missing_or_oversized_html_is_rejected(markup: str) -> None:
    with pytest.raises(ValueError):
        policies.extract_document_policy_clauses(METRICS, markup)
