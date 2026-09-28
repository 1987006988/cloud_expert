import re
from decimal import Decimal

from cloud_expert.database.enums import AvailabilityStatus, ReviewStatus
from cloud_expert.ingestion.providers.aliyun.common import (
    ALIYUN_PUBLIC_CN_PARTITION,
    PARSER_VERSION,
    is_mainland_region_code,
)
from cloud_expert.normalization.percentages import normalize_percentage
from cloud_expert.normalization.units import normalize_days
from cloud_expert.parsing.html_adapter import HtmlDocument, HtmlTable
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord

STORAGE_CLASS_CODES = {
    "标准存储": "standard",
    "低频访问存储": "infrequent_access",
    "低频访问": "infrequent_access",
    "归档存储": "archive",
    "冷归档存储": "cold_archive",
    "深度冷归档存储": "deep_cold_archive",
}
REGION_CODE_PATTERN = re.compile(r"\bcn-[a-z0-9-]+\b")


def parse_oss_document(
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
                target_identity="oss",
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
    official_name = "对象存储 OSS"
    fields = [
        _candidate(
            field_code="product.official_name",
            raw_value=official_name,
            raw_unit=None,
            normalized_value=official_name,
            canonical_unit=None,
            locator="html:h1",
            excerpt=heading or official_name,
            parser_rule="aliyun.oss.product.official_name",
            target_table="product",
            target_identity="oss",
            confidence=0.9,
            section_title="product heading",
        )
    ]
    paragraphs = document.paragraphs_containing("对象存储", "OSS", "Object Storage Service")
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
                parser_rule="aliyun.oss.product.description",
                target_table="product",
                target_identity="oss",
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
    if "storage" not in source_id and "overview" not in source_id and "product" not in source_id:
        return []
    records: list[ParsedRecord] = []
    seen: set[str] = set()
    for class_name, tier_code in STORAGE_CLASS_CODES.items():
        if tier_code in seen:
            continue
        location = _storage_class_location(document, class_name)
        if location is None:
            continue
        locator, excerpt = location
        seen.add(tier_code)
        records.append(
            ParsedRecord(
                record_type="aliyun_oss_storage_class",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity=tier_code,
                fields=_storage_class_fields(class_name, tier_code, locator, excerpt),
                parser_version=PARSER_VERSION,
            )
        )
    return records


def _storage_class_fields(
    class_name: str,
    tier_code: str,
    locator: str,
    excerpt: str,
) -> list[FieldCandidate]:
    fields = [
        _candidate(
            field_code="oss.storage_class.official_name",
            raw_value=class_name,
            raw_unit=None,
            normalized_value=class_name,
            canonical_unit=None,
            locator=locator,
            excerpt=excerpt,
            parser_rule="aliyun.oss.storage_class.name",
            target_table="service_tier",
            target_identity=tier_code,
            confidence=0.88,
            section_title="OSS storage class",
        )
    ]
    days = _minimum_days(excerpt)
    if days:
        fields.append(
            _candidate(
                field_code="object_storage.minimum_storage_duration_days",
                raw_value=days[0],
                raw_unit="day",
                normalized_value=days[1],
                canonical_unit="day",
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.oss.storage_class.minimum_days",
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.82,
                section_title="OSS storage class",
            )
        )
    if "64 KB" in excerpt or "64KB" in excerpt:
        fields.append(
            _candidate(
                field_code="object_storage.minimum_billable_object_size_kib",
                raw_value="64 KB",
                raw_unit="KiB",
                normalized_value=Decimal("64"),
                canonical_unit="KiB",
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.oss.storage_class.minimum_billable_size",
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.86,
                section_title="OSS storage class",
            )
        )
    retrieval = _retrieval_text(excerpt)
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
                parser_rule="aliyun.oss.storage_class.retrieval",
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.76,
                section_title="OSS storage class",
            )
        )
    redundancy = _redundancy(excerpt)
    if redundancy:
        fields.append(
            _candidate(
                field_code="object_storage.redundancy_type",
                raw_value=redundancy,
                raw_unit=None,
                normalized_value=redundancy,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.oss.storage_class.redundancy",
                target_table="service_tier",
                target_identity=tier_code,
                confidence=0.78,
                section_title="OSS storage class",
            )
        )
    for field_code, keyword, rule in (
        ("object_storage.durability_percentage", "持久性", "aliyun.oss.storage_class.durability"),
        (
            "object_storage.availability_percentage",
            "可用性",
            "aliyun.oss.storage_class.availability",
        ),
    ):
        percent = _percentage_near(excerpt, keyword)
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
                confidence=0.8,
                section_title="OSS storage class",
            )
        )
    return fields


def _capability_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    rules = (
        ("lifecycle", "object_storage.lifecycle_management_supported", "生命周期", "Lifecycle"),
        ("versioning", "object_storage.versioning_supported", "版本控制", "Versioning"),
        (
            "replication",
            "object_storage.cross_region_replication_supported",
            "跨区域复制",
            "Replication",
        ),
        (
            "encryption",
            "object_storage.server_side_encryption_supported",
            "服务端加密",
            "Encryption",
        ),
        ("worm", "object_storage.object_lock_supported", "保留策略", "WORM"),
        (
            "static_website",
            "object_storage.static_website_hosting_supported",
            "静态网站",
            "Static website",
        ),
        (
            "access_network",
            "object_storage.transfer_acceleration_supported",
            "传输加速",
            "Transfer acceleration",
        ),
        (
            "access_network",
            "object_storage.dual_stack_endpoint_supported",
            "双栈",
            "Dual-stack endpoint",
        ),
    )
    fields: list[FieldCandidate] = []
    for source_token, field_code, keyword, title in rules:
        if source_token not in source_id:
            continue
        location = _first_location(document, keyword)
        if location is None:
            continue
        locator, excerpt = location
        fields.append(
            _candidate(
                field_code=field_code,
                raw_value="支持",
                raw_unit=None,
                normalized_value=True,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule=f"aliyun.oss.capability.{field_code.rsplit('.', 1)[-1]}",
                target_table="product_specification",
                target_identity="oss",
                confidence=0.82,
                section_title=title,
            )
        )
        if source_token == "encryption" and ("KMS" in excerpt or "密钥管理" in excerpt):
            fields.append(
                _candidate(
                    field_code="object_storage.customer_managed_key_supported",
                    raw_value="支持",
                    raw_unit=None,
                    normalized_value=True,
                    canonical_unit=None,
                    locator=locator,
                    excerpt=excerpt,
                    parser_rule="aliyun.oss.capability.customer_managed_kms_key",
                    target_table="product_specification",
                    target_identity="oss",
                    confidence=0.8,
                    section_title=title,
                )
            )
    if not fields:
        return []
    return [
        ParsedRecord(
            record_type="aliyun_oss_capability",
            source_id=source_id,
            snapshot_id=snapshot_id,
            target_identity="oss",
            fields=fields,
            parser_version=PARSER_VERSION,
        )
    ]


def _region_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    if "regions" not in source_id:
        return []
    records: list[ParsedRecord] = []
    seen: set[str] = set()
    for table in document.tables():
        header_map = _region_header_map(table)
        code_index = header_map.get("region_code")
        if code_index is None:
            continue
        for row_index, row in enumerate(table.rows):
            region_code = _cell(row, code_index)
            if not region_code or not is_mainland_region_code(region_code) or region_code in seen:
                continue
            seen.add(region_code)
            name = _cell(row, header_map.get("region_name")) or region_code
            excerpt = " | ".join(row)
            locator = f"{table.locator}:row[{row_index}]"
            records.append(
                _region_record(source_id, snapshot_id, region_code, name, locator, excerpt)
            )
    if records:
        return records
    return _region_records_from_text(document, source_id, snapshot_id)


def _region_records_from_text(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    records: list[ParsedRecord] = []
    seen: set[str] = set()
    text = _domestic_region_text(document.text)
    for match in REGION_CODE_PATTERN.finditer(text):
        region_code = match.group(0)
        if not is_mainland_region_code(region_code) or region_code in seen:
            continue
        seen.add(region_code)
        excerpt = text[max(match.start() - 120, 0) : match.start() + 500]
        region_name = _region_name_from_excerpt(excerpt, region_code) or region_code
        locator = f"html:text:oss_region[{len(seen)}]"
        records.append(
            _region_record(source_id, snapshot_id, region_code, region_name, locator, excerpt)
        )
    return records


def _region_record(
    source_id: str,
    snapshot_id: str,
    region_code: str,
    region_name: str,
    locator: str,
    excerpt: str,
) -> ParsedRecord:
    return ParsedRecord(
        record_type="region_availability",
        source_id=source_id,
        snapshot_id=snapshot_id,
        target_identity=region_code,
        fields=[
            _candidate(
                field_code="cloud.partition",
                raw_value=ALIYUN_PUBLIC_CN_PARTITION,
                raw_unit=None,
                normalized_value=ALIYUN_PUBLIC_CN_PARTITION,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.oss.region.partition",
                target_table="availability",
                target_identity=region_code,
                confidence=0.9,
                section_title="OSS regions and endpoints",
            ),
            _candidate(
                field_code="region.code",
                raw_value=region_code,
                raw_unit=None,
                normalized_value=region_code,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.oss.region.code",
                target_table="availability",
                target_identity=region_code,
                confidence=0.9,
                section_title="OSS regions and endpoints",
            ),
            _candidate(
                field_code="region.name",
                raw_value=region_name,
                raw_unit=None,
                normalized_value=region_name,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.oss.region.name",
                target_table="availability",
                target_identity=region_code,
                confidence=0.84,
                section_title="OSS regions and endpoints",
            ),
            _candidate(
                field_code="availability.status",
                raw_value=AvailabilityStatus.AVAILABLE.value,
                raw_unit=None,
                normalized_value=AvailabilityStatus.AVAILABLE.value,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.oss.region.available",
                target_table="availability",
                target_identity=region_code,
                confidence=0.82,
                section_title="OSS regions and endpoints",
            ),
        ],
        parser_version=PARSER_VERSION,
    )


def _sla_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    if not source_id.endswith("_sla"):
        return []
    match = re.search(r"服务可用性[^。；;]{0,160}?不低于\s*(\d+(?:\.\d+)?%)", document.text)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?%)", document.text)
    if not match:
        return []
    raw_value = match.group(1)
    excerpt = document.text[max(match.start() - 120, 0) : match.end() + 360]
    if "服务可用性=" in excerpt or "每5分钟错误率" in excerpt:
        return []
    return [
        ParsedRecord(
            record_type="product_sla",
            source_id=source_id,
            snapshot_id=snapshot_id,
            target_identity="oss_service_commitment",
            fields=[
                _candidate(
                    field_code="sla.availability_percentage",
                    raw_value=raw_value,
                    raw_unit="percent",
                    normalized_value=normalize_percentage(raw_value),
                    canonical_unit="percent",
                    locator="html:text:sla:oss_service_commitment",
                    excerpt=excerpt,
                    parser_rule="aliyun.oss.sla.availability_commitment",
                    target_table="product_sla",
                    target_identity="oss_service_commitment",
                    confidence=0.78,
                    section_title="OSS SLA",
                )
            ],
            parser_version=PARSER_VERSION,
        )
    ]


def _storage_class_location(document: HtmlDocument, class_name: str) -> tuple[str, str] | None:
    matches = document.paragraphs_containing(class_name)
    if matches:
        for locator, text in matches:
            if any(token in text for token in ("最低存储时间", "最小计量", "访问", "冗余")):
                return locator, text
        return matches[0]
    index = document.text.find(class_name)
    if index < 0:
        return None
    return f"html:text:storage_class:{class_name}", document.text[index : index + 900]


def _minimum_days(text: str) -> tuple[str, int] | None:
    match = re.search(r"最低存储时间[^\d]{0,20}(\d+)\s*天", text)
    if not match:
        match = re.search(r"(\d+)\s*天", text)
    if not match:
        return None
    normalized, _unit = normalize_days(match.group(1))
    return (match.group(0), normalized) if normalized is not None else None


def _retrieval_text(text: str) -> str | None:
    match = re.search(
        r"(实时访问|解冻[^。；;]{0,80}|归档直读[^。；;]{0,80}|12/48\s*小时|1\s*~\s*12\s*小时)", text
    )
    return match.group(0) if match else None


def _redundancy(text: str) -> str | None:
    zrs_present = "同城冗余" in text or "ZRS" in text
    lrs_present = "本地冗余" in text or "单可用区" in text or "LRS" in text
    if zrs_present and lrs_present:
        return None
    if zrs_present:
        return "ZRS"
    if lrs_present:
        return "LRS"
    return None


def _percentage_near(text: str, keyword: str) -> str | None:
    index = text.find(keyword)
    if index < 0:
        return None
    match = re.search(r"\d+(?:\.\d+)?\s*%", text[index : index + 180])
    return match.group(0) if match else None


def _first_location(document: HtmlDocument, keyword: str) -> tuple[str, str] | None:
    matches = document.paragraphs_containing(keyword)
    if matches:
        return matches[0]
    index = document.text.find(keyword)
    if index < 0:
        return None
    return f"html:text:{keyword}", document.text[max(index - 80, 0) : index + 620]


def _region_header_map(table: HtmlTable) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(table.headers):
        normalized = _normalize_header(header)
        if "地域id" in normalized or "regionid" in normalized:
            mapping["region_code"] = index
        elif "地域" in header and "id" not in normalized:
            mapping["region_name"] = index
    return mapping


def _normalize_header(value: str) -> str:
    return re.sub(r"[\s/_:：()（）-]+", "", value.lower())


def _cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    value = " ".join(row[index].split())
    return value or None


def _domestic_region_text(text: str) -> str:
    start = text.find("亚太-中国")
    if start < 0:
        start = text.find("公共云")
    if start < 0:
        start = 0
    end = text.find("亚太-其他", start)
    if end < 0:
        end = text.find("其他国家和地区", start)
    if end < 0:
        end = len(text)
    return text[start:end]


def _region_name_from_excerpt(excerpt: str, region_code: str) -> str | None:
    index = excerpt.find(region_code)
    if index <= 0:
        return None
    before = excerpt[max(0, index - 80) : index]
    candidates = re.findall(r"([\u4e00-\u9fff]+\s*\d?\s*（[^）]+）|[\u4e00-\u9fff]+)", before)
    return candidates[-1].strip() if candidates else None
