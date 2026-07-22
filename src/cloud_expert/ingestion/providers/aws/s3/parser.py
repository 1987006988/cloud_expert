import re
from decimal import Decimal

from cloud_expert.database.enums import AvailabilityStatus, ReviewStatus
from cloud_expert.ingestion.providers.aws.common import (
    AWS_COMMERCIAL_PARTITION,
    PARSER_VERSION,
)
from cloud_expert.normalization.percentages import normalize_percentage
from cloud_expert.normalization.units import normalize_days, normalize_memory_to_gib, parse_decimal
from cloud_expert.parsing.html_adapter import HtmlDocument, HtmlTable
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord

REGION_CODE_PATTERN = re.compile(r"^(?!cn-)(?!us-gov-)[a-z]{2}-[a-z-]+-\d+$")


def parse_s3_document(
    document: HtmlDocument,
    *,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    records: list[ParsedRecord] = []
    product_fields = _parse_product_fields(document)
    if product_fields:
        records.append(
            ParsedRecord(
                record_type="product",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity="s3",
                fields=product_fields,
                parser_version=PARSER_VERSION,
            )
        )
    records.extend(_storage_class_records(document, source_id, snapshot_id))
    records.extend(_capability_records(document, source_id, snapshot_id))
    records.extend(_region_records(document, source_id, snapshot_id))
    records.extend(_sla_records(document, source_id, snapshot_id))
    return records


def _candidate(
    *,
    field_code: str,
    raw_value: object,
    raw_unit: str | None,
    normalized_value: object,
    canonical_unit: str | None,
    locator: str,
    excerpt: str,
    parser_rule: str,
    target_table: str,
    target_identity: str,
    confidence: float = 0.86,
    section_title: str | None = None,
) -> FieldCandidate:
    return FieldCandidate(
        field_code=field_code,
        raw_value=raw_value,
        raw_unit=raw_unit,
        normalized_value=normalized_value,
        canonical_unit=canonical_unit,
        locator=locator,
        excerpt=excerpt[:800],
        confidence=confidence,
        review_status=ReviewStatus.MACHINE_EXTRACTED.value
        if confidence >= 0.8
        else ReviewStatus.PENDING_REVIEW.value,
        parser_rule=parser_rule,
        target_table=target_table,
        target_identity=target_identity,
        section_title=section_title,
    )


def _parse_product_fields(document: HtmlDocument) -> list[FieldCandidate]:
    heading = document.first_heading()
    official_name = "Amazon Simple Storage Service (Amazon S3)"
    fields = [
        _candidate(
            field_code="product.official_name",
            raw_value=official_name,
            raw_unit=None,
            normalized_value=official_name,
            canonical_unit=None,
            locator="html:h1",
            excerpt=heading or official_name,
            parser_rule="aws.s3.product.official_name",
            target_table="product",
            target_identity="s3",
            confidence=0.9,
            section_title="product heading",
        )
    ]
    paragraphs = document.paragraphs_containing("Amazon S3", "Simple Storage Service")
    if paragraphs:
        locator, excerpt = paragraphs[0]
        fields.append(
            _candidate(
                field_code="product.description",
                raw_value=excerpt,
                raw_unit=None,
                normalized_value=excerpt,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.s3.product.description",
                target_table="product",
                target_identity="s3",
                confidence=0.84,
                section_title="product description",
            )
        )
    return fields


def _storage_class_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    records: list[ParsedRecord] = []
    for table in document.tables():
        header_map = _storage_header_map(table)
        class_index = header_map.get("storage_class")
        if class_index is None:
            continue
        for row_index, row in enumerate(table.rows):
            class_name = _cell(row, class_index)
            if not class_name or "S3" not in class_name:
                continue
            tier_code = _storage_class_code(class_name)
            excerpt = " | ".join(row)
            locator = f"{table.locator}:row[{row_index}]"
            fields = _storage_class_fields(row, header_map, class_name, tier_code, locator, excerpt)
            records.append(
                ParsedRecord(
                    record_type="s3_storage_class",
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    target_identity=tier_code,
                    fields=fields,
                    parser_version=PARSER_VERSION,
                )
            )
    return records


def _storage_class_fields(
    row: list[str],
    header_map: dict[str, int],
    class_name: str,
    tier_code: str,
    locator: str,
    excerpt: str,
) -> list[FieldCandidate]:
    fields = [
        _candidate(
            field_code="s3.storage_class.official_name",
            raw_value=class_name,
            raw_unit=None,
            normalized_value=class_name,
            canonical_unit=None,
            locator=locator,
            excerpt=excerpt,
            parser_rule="aws.s3.storage_class.name",
            target_table="service_tier",
            target_identity=tier_code,
            confidence=0.9,
            section_title="S3 storage class table",
        )
    ]
    duration = _cell(row, header_map.get("minimum_duration"))
    if duration:
        days = _duration_to_days(duration)
        fields.append(
            _candidate(
                field_code="object_storage.minimum_storage_duration_days",
                raw_value=duration,
                raw_unit="day",
                normalized_value=days,
                canonical_unit="day",
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.s3.storage_class.minimum_duration",
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.82 if days is not None else 0.66,
                section_title="S3 storage class table",
            )
        )
    for key, field_code, rule in (
        ("durability", "object_storage.durability_percentage", "aws.s3.storage_class.durability"),
        (
            "availability",
            "object_storage.availability_percentage",
            "aws.s3.storage_class.availability",
        ),
    ):
        raw_value = _cell(row, header_map.get(key))
        percent = _percentage_from_text(raw_value or "")
        if percent is None:
            continue
        fields.append(
            _candidate(
                field_code=field_code,
                raw_value=percent,
                raw_unit="percent",
                normalized_value=normalize_percentage(percent),
                canonical_unit="percent",
                locator=locator,
                excerpt=excerpt,
                parser_rule=rule,
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.84,
                section_title="S3 storage class table",
            )
        )
    retrieval = _cell(row, header_map.get("retrieval"))
    if retrieval:
        fields.append(
            _candidate(
                field_code="object_storage.retrieval_time_description",
                raw_value=retrieval,
                raw_unit=None,
                normalized_value=retrieval,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.s3.storage_class.retrieval",
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.76,
                section_title="S3 storage class table",
            )
        )
    minimum_object = _cell(row, header_map.get("minimum_object_size"))
    if minimum_object:
        value = _minimum_object_size_kib(minimum_object)
        fields.append(
            _candidate(
                field_code="object_storage.minimum_billable_object_size_kib",
                raw_value=minimum_object,
                raw_unit="KiB",
                normalized_value=value,
                canonical_unit="KiB",
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.s3.storage_class.minimum_billable_object",
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.8 if value is not None else 0.64,
                section_title="S3 storage class table",
            )
        )
    return fields


def _capability_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    fields: list[FieldCandidate] = []
    source_rules = (
        ("multipart", "object_storage.multipart_upload_supported", "multipart", "Multipart upload"),
        ("versioning", "object_storage.versioning_supported", "versioning", "Versioning"),
        ("lifecycle", "object_storage.lifecycle_management_supported", "lifecycle", "Lifecycle"),
        ("replication", "object_storage.cross_region_replication_supported", "replication", "Replication"),
        ("object_lock", "object_storage.object_lock_supported", "object lock", "Object Lock"),
        ("encryption", "object_storage.server_side_encryption_supported", "encryption", "Encryption"),
        ("event_notifications", "object_storage.event_notification_supported", "event", "Event notifications"),
        ("static_website", "object_storage.static_website_hosting_supported", "website", "Static website hosting"),
    )
    for source_token, field_code, keyword, section_title in source_rules:
        if source_token not in source_id:
            continue
        location = _first_evidence_location(document, keyword)
        if location is None:
            continue
        locator, excerpt = location
        fields.append(
            _candidate(
                field_code=field_code,
                raw_value="supported",
                raw_unit=None,
                normalized_value=True,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule=f"aws.s3.capability.{source_token}",
                target_table="product_specification",
                target_identity="s3",
                confidence=0.82,
                section_title=section_title,
            )
        )
        if source_token == "encryption" and "kms" in source_id.lower():
            fields.append(
                _candidate(
                    field_code="object_storage.customer_managed_key_supported",
                    raw_value="supported",
                    raw_unit=None,
                    normalized_value=True,
                    canonical_unit=None,
                    locator=locator,
                    excerpt=excerpt,
                    parser_rule="aws.s3.capability.customer_managed_kms_key",
                    target_table="product_specification",
                    target_identity="s3",
                    confidence=0.8,
                    section_title=section_title,
                )
            )
    fields.extend(_object_size_fields(document, source_id))
    if not fields:
        return []
    return [
        ParsedRecord(
            record_type="s3_capability",
            source_id=source_id,
            snapshot_id=snapshot_id,
            target_identity="s3",
            fields=fields,
            parser_version=PARSER_VERSION,
        )
    ]


def _object_size_fields(document: HtmlDocument, source_id: str) -> list[FieldCandidate]:
    if "multipart" not in source_id:
        return []
    fields: list[FieldCandidate] = []
    text = document.text
    max_object_match = re.search(r"(?:maximum|largest)[^.]{0,120}?(5\s*(?:TiB|TB))", text, re.IGNORECASE)
    if max_object_match:
        raw_value = max_object_match.group(1)
        value, unit = normalize_memory_to_gib(raw_value)
        fields.append(
            _candidate(
                field_code="object_storage.max_object_size_gib",
                raw_value=raw_value,
                raw_unit="TiB",
                normalized_value=value,
                canonical_unit=unit,
                locator="html:text:s3:max_object_size",
                excerpt=_excerpt_around(text, raw_value),
                parser_rule="aws.s3.multipart.max_object_size",
                target_table="product_specification",
                target_identity="s3",
                confidence=0.82 if value is not None else 0.6,
                section_title="S3 multipart upload",
            )
        )
    single_upload_match = re.search(r"(?:single|PUT)[^.]{0,120}?(5\s*(?:GiB|GB))", text, re.IGNORECASE)
    if single_upload_match:
        raw_value = single_upload_match.group(1)
        value, unit = normalize_memory_to_gib(raw_value)
        fields.append(
            _candidate(
                field_code="object_storage.max_single_upload_size_gib",
                raw_value=raw_value,
                raw_unit="GiB",
                normalized_value=value,
                canonical_unit=unit,
                locator="html:text:s3:max_single_upload_size",
                excerpt=_excerpt_around(text, raw_value),
                parser_rule="aws.s3.multipart.max_single_upload_size",
                target_table="product_specification",
                target_identity="s3",
                confidence=0.78 if value is not None else 0.58,
                section_title="S3 multipart upload",
            )
        )
    return fields


def _region_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    if not source_id.endswith("_regions") and "endpoints" not in source_id:
        return []
    records: list[ParsedRecord] = []
    for table in document.tables():
        header_map = _region_header_map(table)
        code_index = header_map.get("region_code")
        if code_index is None:
            continue
        for row_index, row in enumerate(table.rows):
            region_code = _cell(row, code_index)
            if not region_code or not REGION_CODE_PATTERN.match(region_code):
                continue
            name = _cell(row, header_map.get("region_name")) or region_code
            excerpt = " | ".join(row)
            locator = f"{table.locator}:row[{row_index}]"
            records.append(
                ParsedRecord(
                    record_type="region_availability",
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    target_identity=region_code,
                    fields=[
                        _candidate(
                            field_code="cloud.partition",
                            raw_value=AWS_COMMERCIAL_PARTITION,
                            raw_unit=None,
                            normalized_value=AWS_COMMERCIAL_PARTITION,
                            canonical_unit=None,
                            locator=locator,
                            excerpt=excerpt,
                            parser_rule="aws.s3.region.partition",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.9,
                            section_title="S3 endpoints table",
                        ),
                        _candidate(
                            field_code="region.code",
                            raw_value=region_code,
                            raw_unit=None,
                            normalized_value=region_code,
                            canonical_unit=None,
                            locator=locator,
                            excerpt=excerpt,
                            parser_rule="aws.s3.region.code",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.92,
                            section_title="S3 endpoints table",
                        ),
                        _candidate(
                            field_code="region.name",
                            raw_value=name,
                            raw_unit=None,
                            normalized_value=name,
                            canonical_unit=None,
                            locator=locator,
                            excerpt=excerpt,
                            parser_rule="aws.s3.region.name",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.9,
                            section_title="S3 endpoints table",
                        ),
                        _candidate(
                            field_code="availability.status",
                            raw_value=AvailabilityStatus.AVAILABLE.value,
                            raw_unit=None,
                            normalized_value=AvailabilityStatus.AVAILABLE.value,
                            canonical_unit=None,
                            locator=locator,
                            excerpt=excerpt,
                            parser_rule="aws.s3.region.available",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.84,
                            section_title="S3 endpoints table",
                        ),
                    ],
                    parser_version=PARSER_VERSION,
                )
            )
    return records


def _sla_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    if not source_id.endswith("_sla"):
        return []
    candidates = []
    for keyword in ("Service Commitment", "Monthly Uptime Percentage"):
        location = _first_evidence_location(document, keyword)
        if location is None:
            continue
        locator, excerpt = location
        percent = _percentage_from_text(excerpt)
        if percent is None:
            continue
        candidates.append((locator, excerpt, percent))
    if not candidates:
        percent = _percentage_from_text(document.text)
        if percent:
            candidates.append(("html:text:s3:sla", _excerpt_around(document.text, percent), percent))
    if not candidates:
        return []
    locator, excerpt, percent = candidates[0]
    return [
        ParsedRecord(
            record_type="product_sla",
            source_id=source_id,
            snapshot_id=snapshot_id,
            target_identity="s3_service_commitment",
            fields=[
                _candidate(
                    field_code="sla.availability_percentage",
                    raw_value=percent,
                    raw_unit="percent",
                    normalized_value=normalize_percentage(percent),
                    canonical_unit="percent",
                    locator=locator,
                    excerpt=excerpt,
                    parser_rule="aws.s3.sla.availability_commitment",
                    target_table="product_sla",
                    target_identity="s3_service_commitment",
                    confidence=0.76,
                    section_title="S3 SLA",
                )
            ],
            parser_version=PARSER_VERSION,
        )
    ]


def _storage_header_map(table: HtmlTable) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(table.headers):
        normalized = _normalize_header(header)
        if "storageclass" in normalized:
            mapping["storage_class"] = index
        elif "durability" in normalized:
            mapping["durability"] = index
        elif "availability" in normalized:
            mapping["availability"] = index
        elif "minimumstorageduration" in normalized or "minimumduration" in normalized:
            mapping["minimum_duration"] = index
        elif "retrieval" in normalized or "access" in normalized:
            mapping["retrieval"] = index
        elif "minimum" in normalized and ("object" in normalized or "size" in normalized):
            mapping["minimum_object_size"] = index
    return mapping


def _region_header_map(table: HtmlTable) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(table.headers):
        normalized = _normalize_header(header)
        if normalized in {"region", "regioncode"}:
            mapping["region_code"] = index
        elif "regionname" in normalized:
            mapping["region_name"] = index
    return mapping


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    value = " ".join(row[index].split())
    return value or None


def _storage_class_code(class_name: str) -> str:
    normalized = class_name.replace("Amazon", "").strip().lower()
    normalized = normalized.replace("s3 ", "s3_").replace(" - ", "_")
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _duration_to_days(raw_value: str) -> int | None:
    lowered = raw_value.lower()
    if "none" in lowered or "n/a" in lowered:
        return 0
    normalized, _unit = normalize_days(raw_value)
    return normalized


def _minimum_object_size_kib(raw_value: str) -> Decimal | None:
    value = parse_decimal(raw_value)
    if value is None:
        return None
    lowered = raw_value.lower()
    if "mib" in lowered or "mb" in lowered:
        return value * Decimal("1024")
    if "gib" in lowered or "gb" in lowered:
        return value * Decimal("1048576")
    return value


def _first_evidence_location(document: HtmlDocument, keyword: str) -> tuple[str, str] | None:
    matches = document.paragraphs_containing(keyword, keyword.title(), keyword.upper())
    if matches:
        return matches[0]
    lowered = document.text.lower()
    index = lowered.find(keyword.lower())
    if index < 0:
        return None
    return f"html:text:{keyword.lower().replace(' ', '_')}", document.text[index : index + 700]


def _percentage_from_text(text: str) -> str | None:
    match = re.search(r"\d+(?:\.\d+)?\s*%", text)
    return match.group(0) if match else None


def _excerpt_around(text: str, keyword: str, radius: int = 700) -> str:
    index = text.find(keyword)
    if index < 0:
        return text[:radius]
    start = max(index - 120, 0)
    return text[start : start + radius]
