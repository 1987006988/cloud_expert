"""Read-only, scoped evidence planning for four licensed AWS documentation sources.

Integration: call ``prepare_document_policy(session, snapshot_id, raw_root=...,
as_of=...)`` against a captured, current SourceDocument/SnapshotRecord. The
coordinator may pass its ``records`` to ``aws_billing_policy.evidence_row`` in a
separate transaction. Rebuild the plan immediately before applying it; this
module never writes Evidence, approves Price, calculates TCO, or changes Gates.

Each canonical JSON excerpt binds the raw SHA-256, manifest and registry hashes,
source/document/snapshot IDs, exact URL, license attribution, full DOM clause
and context, interpretation and limitations. ``css:`` locators address the
captured HTML, not a live page. Extract-only results are unverified candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any

from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import Session

from cloud_expert.database.models.snapshot import SnapshotRecord
from cloud_expert.ingestion.registry.loader import get_entry_by_source_id
from cloud_expert.ingestion.registry.schemas import SourceRegistryEntry
from cloud_expert.pricing.aws_billing_policy import canonical, digest, snapshot_binding, utc
from cloud_expert.pricing.official_catalog import decode_catalog_json

RULE = "aws_document_policy_v1"
MAX_HTML_BYTES = 2_097_152
LICENSE = "CC-BY-SA-4.0"


@dataclass(frozen=True)
class DocumentScope:
    url: str
    product_code: str | None
    heading_id: str
    heading: str
    scope: str


DOCUMENTS = {
    "aws_pricing_principles": DocumentScope(
        "https://docs.aws.amazon.com/whitepapers/latest/how-aws-pricing-works/key-principles.html",
        None,
        "key-principles",
        "Key principles",
        "general_aws_pricing_principles_only",
    ),
    "aws_s3_storage_metrics_units": DocumentScope(
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage_lens_metrics_glossary.html",
        "s3",
        "storage_lens_metrics_glossary",
        "Amazon S3 Storage Lens metrics glossary",
        "storage_metrics_only",
    ),
    "aws_s3_billing_usage_codes": DocumentScope(
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/aws-usage-report-understand.html",
        "s3",
        "aws-usage-report-understand",
        "Understanding your AWS billing and usage reports for Amazon S3",
        "billing_usage_codes_only",
    ),
    "aws_ec2_instance_lifecycle_billing": DocumentScope(
        "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html",
        "ec2",
        "ec2-instance-lifecycle",
        "Amazon EC2 instance state changes",
        "ec2_instance_usage_lifecycle_only",
    ),
}


def _scope(source_id: str) -> DocumentScope:
    if source_id not in DOCUMENTS:
        raise ValueError("unsupported AWS document source ID")
    return DOCUMENTS[source_id]


def _read(root: Path, relative: str, limit: int) -> bytes:
    windows = PureWindowsPath(relative)
    if (
        not relative
        or windows.drive
        or windows.root
        or ".." in windows.parts
        or Path(relative).is_absolute()
    ):
        raise ValueError("snapshot path must be relative and contained in raw root")
    path = (root.resolve() / windows.as_posix()).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("snapshot path escapes raw root or is missing")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("snapshot file is empty or oversized")
    return raw


def _verify(
    snapshot: SnapshotRecord,
    entry: SourceRegistryEntry,
    root: Path,
    as_of: datetime,
    max_age_days: int,
) -> tuple[dict[str, Any], bytes]:
    spec = _scope(snapshot.source_id)
    captured = utc(snapshot.captured_at)
    if (
        entry.source_id != snapshot.source_id
        or entry.url != spec.url
        or entry.product_code != spec.product_code
        or entry.provider_code != "aws"
        or entry.market_mode != "international"
        or entry.cloud_partition != "aws"
        or entry.source_type != "documentation"
        or entry.authority_level != "official_primary"
        or entry.terms_review_status != "approved"
        or entry.reviewed_at is None
        or not entry.enabled
        or not entry.allow_automated_fetch
        or entry.automated_fetch_allowed is not True
        or entry.manual_only
        or entry.requires_authentication
        or entry.requires_browser
        or entry.fixture_response_path is not None
        or entry.robots_allowed is not True
        or entry.robots_checked_at is None
        or LICENSE not in (entry.compliance_notes or "")
        or "docs.aws.amazon.com" not in (entry.compliance_notes or "")
        or entry.domain_policy.allowed_domains != ["docs.aws.amazon.com"]
        or entry.domain_policy.allow_subdomains
        or entry.domain_policy.allow_redirects
        or entry.domain_policy.allowed_redirect_domains
        or "text/html" not in entry.expected_content_type
    ):
        raise ValueError("document registry scope or license approval is invalid")
    if any(
        reviewed.tzinfo is None or utc(reviewed) > captured
        for reviewed in (entry.reviewed_at, entry.robots_checked_at)
    ):
        raise ValueError("capture must follow dated license and robots approval")
    doc = snapshot.source_document
    if (
        type(snapshot.id) is not int
        or snapshot.id <= 0
        or doc is None
        or type(doc.id) is not int
        or doc.id <= 0
        or doc.id != snapshot.source_document_id
        or doc.provider is None
        or doc.provider.code != "aws"
        or doc.provider_id != doc.provider.id
        or doc.url != spec.url
        or doc.cloud_partition != "aws"
        or doc.source_type != "documentation"
        or doc.authority_level != "official_primary"
        or doc.is_current is not True
        or snapshot.is_current is not True
        or doc.content_hash != snapshot.content_hash
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot.content_hash)
        or doc.storage_path != snapshot.storage_path
        or doc.mime_type != "text/html"
        or snapshot.content_type != "text/html"
        or doc.http_status != 200
        or utc(doc.captured_at) != captured
        or not timedelta(0) <= utc(as_of) - captured <= timedelta(days=max_age_days)
        or type(snapshot.content_length_bytes) is not int
        or not 0 < snapshot.content_length_bytes <= MAX_HTML_BYTES
    ):
        raise ValueError("document snapshot scope, current status or metadata mismatch")
    manifest = decode_catalog_json(_read(root, snapshot.manifest_path, 1_048_576))
    expected = {
        "schema_version": "1.0",
        "source_id": entry.source_id,
        "provider_code": "aws",
        "market_mode": "international",
        "product_code": spec.product_code,
        "source_type": "documentation",
        "requested_url": spec.url,
        "final_url": spec.url,
        "http_status": 200,
        "storage_path": snapshot.storage_path,
        "content_sha256": snapshot.content_hash,
        "content_length_bytes": snapshot.content_length_bytes,
        "content_type": "text/html",
    }
    if not isinstance(manifest, dict) or any(
        key not in manifest
        or type(manifest.get(key)) is not type(value)
        or manifest.get(key) != value
        for key, value in expected.items()
    ):
        raise ValueError("document snapshot manifest mismatch")
    timestamp = manifest.get("captured_at")
    if not isinstance(timestamp, str):
        raise ValueError("document snapshot manifest timestamp missing")
    manifest_time = datetime.fromisoformat(timestamp)
    if manifest_time.tzinfo is None or utc(manifest_time) != captured:
        raise ValueError("document snapshot manifest timestamp mismatch")
    raw = _read(root, snapshot.storage_path, MAX_HTML_BYTES)
    if len(raw) != snapshot.content_length_bytes or digest(raw) != snapshot.content_hash:
        raise ValueError("document snapshot full content hash or length mismatch")
    return manifest, raw


def _text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def _one(nodes: list[Tag], description: str) -> Tag:
    if len(nodes) != 1:
        raise ValueError(f"required document clause missing or ambiguous: {description}")
    return nodes[0]


def _paragraph(body: Tag, start: str) -> Tag:
    return _one([p for p in body.find_all("p") if _text(p).startswith(start)], start)


def _require(node: Tag, *phrases: str) -> None:
    if not all(phrase in _text(node) for phrase in phrases):
        raise ValueError("document clause changed or required qualifier missing")


def _section(node: Tag, section_id: str) -> None:
    section = node.find_previous("h2")
    if section is None or section.get("id") != section_id:
        raise ValueError("document clause is outside its expected section")


def _locator(node: Tag) -> str:
    parts = []
    current: Tag | None = node
    while current is not None and current.get("id") != "main-col-body":
        index = len(current.find_previous_siblings(current.name)) + 1
        parts.append(f"{current.name}:nth-of-type({index})")
        current = current.parent
    if current is None:
        raise ValueError("clause is outside document body")
    result = "css:#main-col-body" + "".join(f" > {part}" for part in reversed(parts))
    if len(result) > 512:
        raise ValueError("document locator is too long")
    return result


def _fragment(node: Tag) -> dict[str, str]:
    return {"locator": _locator(node), "text": _text(node), "html": str(node)}


def _clause(
    body: Tag,
    node: Tag,
    kind: str,
    policy: dict[str, Any],
    limitation: str,
    context: list[Tag] | None = None,
) -> dict[str, Any]:
    heading = _one(list(body.find_all("h1")), "page heading")
    section = node.find_previous("h2")
    surrounding = [heading]
    if section is not None and body in section.parents:
        surrounding.append(section)
    surrounding.extend(context or [])
    return {
        "kind": kind,
        "locator": _locator(node),
        "clause": _text(node),
        "clause_html": str(node),
        "context": [_fragment(part) for part in surrounding],
        "policy": policy,
        "limitation": limitation,
        "verification_status": "unverified_candidate",
    }


def _principles(body: Tag) -> list[dict[str, Any]]:
    tax = _paragraph(body, "Except as otherwise noted, AWS prices")
    _require(
        tax,
        "Except as otherwise noted, AWS prices are exclusive of applicable taxes and duties, "
        "including value-added tax (VAT) and sales tax.",
        "For customers with a Japanese billing address, use of AWS is subject to Japanese "
        "Consumption Tax.",
    )
    compute = _one(
        [p for p in body.find_all("p") if "For compute resources," in _text(p)], "compute unit"
    )
    _require(
        compute,
        "For compute resources, you pay by the hour or by the second from the time you launch "
        "a resource until the time you stop or terminate it, unless you have made a reservation "
        "for which the cost is agreed upon beforehand.",
    )
    for node in (tax, compute):
        _section(node, "understand-the-fundamentals-of-pricing")
    return [
        _clause(
            body,
            tax,
            "general_tax_exclusion",
            {
                "tax_status": "tax_excluded_except_as_otherwise_noted",
                "tax_rate": None,
                "customer_payable_tax": "unknown",
            },
            "General AWS principle only; exceptions and billing-address rules apply. "
            "No SKU tax approval, tax rate, exemption or payable-tax calculation.",
        ),
        _clause(
            body,
            compute,
            "general_compute_units",
            {"unit_alternatives": ["hour", "second"], "reservation_exception": True},
            "General principle, not a selected SKU billing unit or rounding rule. "
            "Reservation terms may differ; surrounding transfer/storage text is context only.",
        ),
    ]


def _metrics(body: Tag) -> list[dict[str, Any]]:
    node = _paragraph(body, "The unit of measurement for S3 storage bytes")
    # Preserve exponent structure: flattened 230 or an unrelated superscript is not 2**30.
    math_dom = BeautifulSoup(str(node), "html.parser")
    exponents = math_dom.find_all("sup")
    if [_text(exponent) for exponent in exponents] != ["30", "40", "50"]:
        raise ValueError("storage metric DOM exponents are missing or changed")
    for exponent in exponents:
        exponent.replace_with(f"^({_text(exponent)})")
    math_text = " ".join(math_dom.get_text().split())
    expected = (
        "The unit of measurement for S3 storage bytes is in binary gigabytes (GB), "
        "where 1 GB is 2^(30) bytes, 1 TB is 2^(40) bytes, and 1 PB is 2^(50) bytes. "
        "This unit of measurement is also known as a gibibyte (GiB), as defined by the "
        "International Electrotechnical Commission (IEC)."
    )
    if math_text != expected:
        raise ValueError("storage metric clause or DOM exponent is unsupported")
    return [
        _clause(
            body,
            node,
            "storage_metric_binary_gb",
            {
                "scope": "storage_metrics_only",
                "reported_unit": "GB",
                "metric_unit": "GiB",
                "bytes_per_metric_gb": 2**30,
                "billing_conversion_authorized": False,
            },
            "S3 Storage Lens storage metrics only. Does not establish billing GB, convert any "
            "Price unit, authorize GB-to-GiB billing conversion, or define a monthly duration.",
        )
    ]


def _table(body: Tag, headers: list[str]) -> Tag:
    return _one(
        [t for t in body.find_all("table") if [_text(h) for h in t.find_all("th")] == headers],
        "table headers",
    )


def _row(table: Tag, key: str, width: int) -> tuple[Tag, list[Tag]]:
    rows = []
    for row in table.find_all("tr"):
        cells = list(row.find_all("td", recursive=False))
        if cells and cells[0].get_text("", strip=True) == key:
            rows.append(row)
    node = _one(rows, key)
    cells = list(node.find_all("td", recursive=False))
    if len(cells) != width or any(c.get("rowspan") or c.get("colspan") for c in cells):
        raise ValueError("document table column shape changed")
    return node, cells


def _usage(body: Tag) -> list[dict[str, Any]]:
    table = _table(body, ["Usage Type", "Units", "Granularity", "Description"])
    prefix = _paragraph(body, "Amazon S3 billing and usage reports use codes and abbreviations.")
    _require(prefix, "replace region , region1 , and region2 with abbreviations")
    omitted = _paragraph(body, "For the US East (N. Virginia) Region,")
    _require(omitted, "the region prefix is omitted from usage type codes.")
    headers = _one([r for r in table.find_all("tr") if r.find("th")], "usage headers")
    definitions = [
        (
            "region-TimedStorage-ByteHrs",
            "GB-Month",
            "Daily",
            "storage_usage_code",
            "The number of GB-months that data was stored in S3 Standard storage",
        ),
        (
            "region-Requests-Tier1",
            "Count",
            "Hourly",
            "request_tier1_usage_code",
            "The number of PUT , COPY , or POST requests for S3 Standard, RRS, and tags, "
            "plus LIST requests for all buckets and objects",
        ),
        (
            "region-Requests-Tier2",
            "Count",
            "Hourly",
            "request_tier2_usage_code",
            "The number of GET and all other non-Tier1 requests",
        ),
    ]
    result = []
    for code, unit, granularity, kind, description in definitions:
        node, cells = _row(table, code, 4)
        if [_text(c) for c in cells[1:]] != [unit, granularity, description]:
            raise ValueError("billing usage clause units, granularity or description changed")
        result.append(
            _clause(
                body,
                node,
                kind,
                {
                    "usage_type_pattern": code,
                    "unit_label": unit,
                    "granularity": granularity,
                    "description": description,
                },
                "Only this usage-code row, not all S3 classes or requests. ByteHrs in a code "
                "does not override the Units column. No byte/GB definition, hours/month "
                "conversion, request price denominator, price or complete TCO is established.",
                [headers, prefix, omitted],
            )
        )
    return result


def _lifecycle(body: Tag) -> list[dict[str, Any]]:
    table = _table(body, ["Instance state", "Description", "Instance usage billing"])
    _section(table, "instance-billing-by-state")
    running, cells = _row(table, "running", 3)
    if [_text(c) for c in cells[1:]] != ["The instance is running and ready for use.", "Billed"]:
        raise ValueError("running billing state changed")
    stopping, _ = _row(table, "stopping", 3)
    _require(
        stopping,
        "If you hibernate an instance, you're billed while the instance is in the stopping state.",
    )
    terminated, _ = _row(table, "terminated", 3)
    _require(
        terminated,
        "Reserved Instances that applied to terminated instances are billed "
        "until the end of their term according to their payment option.",
    )
    intro = _paragraph(body, "The following table provides a brief description of each instance")
    _require(
        intro,
        "Some AWS resources, such as Amazon EBS volumes and Elastic IP addresses, "
        "incur charges regardless of the instance's state.",
    )
    node = _paragraph(body, "As soon as your instance transitions to the running state,")
    _section(node, "instance-launch")
    _require(
        node,
        "As soon as your instance transitions to the running state, you're billed "
        "for each second, with a one-minute minimum, that you keep the instance running, "
        "even if the instance remains idle and you don't connect to it.",
    )
    restart = _paragraph(body, "Each time you transition an instance from stopped to running")
    _section(restart, "instance-stop-start")
    _require(
        restart,
        "you are charged per second when the instance is running, with a minimum "
        "of one minute per instance start.",
    )
    return [
        _clause(
            body,
            node,
            "compute_running_lifecycle",
            {
                "billed_state": "running",
                "billing_unit": "second",
                "minimum_seconds_per_start": 60,
                "idle_is_billed": True,
            },
            "EC2 instance usage lifecycle only; not an all-resource stop-billing rule. "
            "Hibernation stopping, Reserved Instance terms, EBS and Elastic IP charges remain "
            "separate. Does not approve SKU prices, OS/tenancy applicability or complete TCO.",
            [intro, table, restart, running],
        )
    ]


def extract_document_policy_clauses(source_id: str, html: str) -> list[dict[str, Any]]:
    """Return unverified candidates; only the snapshot planner supplies provenance."""
    spec = _scope(source_id)
    if not html or len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError("document HTML is empty or oversized")
    soup = BeautifulSoup(html, "html.parser")
    body = _one(list(soup.select("#main-col-body")), "document body")
    heading = _one(list(body.find_all("h1")), "document title")
    if heading.get("id") != spec.heading_id or _text(heading) != spec.heading:
        raise ValueError("document title does not match registered scope")
    extractor = {
        "aws_pricing_principles": _principles,
        "aws_s3_storage_metrics_units": _metrics,
        "aws_s3_billing_usage_codes": _usage,
        "aws_ec2_instance_lifecycle_billing": _lifecycle,
    }[source_id]
    result = extractor(body)
    for clause in result:
        clause.update(
            {
                "scope": spec.scope,
                "product_code": spec.product_code,
                "price_approval": False,
                "tco_eligible": False,
                "customer_eligible": False,
                "billing_conversion_authorized": False,
            }
        )
    return result


def prepare_document_policy(
    session: Session,
    snapshot_id: int,
    *,
    raw_root: Path,
    as_of: datetime,
    max_age_days: int = 14,
) -> dict[str, Any]:
    """Build Evidence-compatible records without autoflush, mutation or approval."""
    if (
        as_of.tzinfo is None
        or type(snapshot_id) is not int
        or snapshot_id <= 0
        or type(max_age_days) is not int
        or not 1 <= max_age_days <= 90
    ):
        raise ValueError("aware as_of, positive snapshot ID and bounded freshness required")
    with session.no_autoflush:
        snapshot = session.get(SnapshotRecord, snapshot_id)
        if snapshot is None or snapshot.id != snapshot_id:
            raise ValueError("document snapshot not found")
        _scope(snapshot.source_id)
        entry = get_entry_by_source_id(snapshot.source_id)
        if entry is None:
            raise ValueError("document source is not registered")
        manifest, raw = _verify(snapshot, entry, raw_root, as_of, max_age_days)
        binding = snapshot_binding(snapshot, entry, manifest)
        title = snapshot.source_document.title
    clauses = extract_document_policy_clauses(entry.source_id, raw.decode("utf-8", errors="strict"))
    records = []
    for clause in clauses:
        excerpt = canonical(
            {
                **clause,
                **binding,
                "rule_version": RULE,
                "verification_status": "snapshot_verified_review_required",
                "market_mode": "international",
                "cloud_partition": "aws",
                "license": {
                    "identifier": LICENSE,
                    "attribution": "Amazon Web Services",
                    "source_title": title,
                    "source_url": entry.url,
                    "notice": entry.compliance_notes,
                    "scope_notes": entry.notes,
                    "adaptation": "DOM extraction and separate scoped interpretation; "
                    "retain attribution and applicable ShareAlike obligations.",
                },
            }
        )
        records.append(
            {
                **binding,
                "kind": clause["kind"],
                "scope": clause["scope"],
                "locator": clause["locator"],
                "excerpt": excerpt,
                "content_hash": digest(excerpt),
                "parser_rule": RULE,
                "evidence_type": "html_section",
            }
        )
    return {
        "binding": binding,
        "records": records,
        "scope": "internal_reference_only",
        "policy_scope": _scope(entry.source_id).scope,
        "review_required": True,
        "price_approval": False,
        "tco_eligible": False,
        "customer_eligible": False,
        "billing_conversion_authorized": False,
    }
