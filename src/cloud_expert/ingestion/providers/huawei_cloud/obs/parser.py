import re

from cloud_expert.database.enums import ReviewStatus
from cloud_expert.ingestion.providers.huawei_cloud.common import PARSER_VERSION
from cloud_expert.ingestion.providers.huawei_cloud.obs.schemas import ObsStorageClassCandidate
from cloud_expert.normalization.obs import normalize_storage_class_code
from cloud_expert.normalization.percentages import normalize_percentage
from cloud_expert.normalization.units import normalize_days
from cloud_expert.parsing.html_adapter import HtmlDocument
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord

STORAGE_CLASS_NAMES = ("标准存储", "低频访问存储", "归档存储", "深度归档存储")


def parse_obs_document(
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
                target_identity="obs",
                fields=product_fields,
                parser_version=PARSER_VERSION,
            )
        )
    if source_id.endswith("_sla"):
        for scope, fields in _parse_sla_fields(document, source_id):
            records.append(
                ParsedRecord(
                    record_type="product_sla",
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    target_identity=scope,
                    fields=fields,
                    parser_version=PARSER_VERSION,
                )
            )
        return records
    for storage_class in _storage_class_candidates(document):
        records.append(
            ParsedRecord(
                record_type="obs_storage_class",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity=storage_class.tier_code,
                fields=_storage_class_fields(storage_class),
                parser_version=PARSER_VERSION,
            )
        )
    capability_fields = _capability_fields(document)
    if capability_fields:
        records.append(
            ParsedRecord(
                record_type="obs_capability",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity="obs",
                fields=capability_fields,
                parser_version=PARSER_VERSION,
            )
        )
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
    official_name = (
        "对象存储服务 OBS"
        if "对象存储服务" in document.text or "Object Storage Service" in document.text
        else heading
    )
    fields = [
        _candidate(
            field_code="product.official_name",
            raw_value=official_name,
            raw_unit=None,
            normalized_value=official_name,
            canonical_unit=None,
            locator="html:h1",
            excerpt=heading
            if official_name == heading
            else _excerpt_around(document.text, "对象存储服务"),
            parser_rule="obs.product.heading",
            target_table="product",
            target_identity="obs",
            confidence=0.9,
            section_title="product heading",
        )
    ]
    paragraphs = document.paragraphs_containing("对象存储服务", "OBS")
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
                parser_rule="obs.product.description",
                target_table="product",
                target_identity="obs",
                confidence=0.86,
                section_title="product description",
            )
        )
    return fields


def _storage_class_candidates(document: HtmlDocument) -> list[ObsStorageClassCandidate]:
    candidates: list[ObsStorageClassCandidate] = []
    seen: set[str] = set()
    for class_name in STORAGE_CLASS_NAMES:
        tier_code = normalize_storage_class_code(class_name)
        if tier_code in seen:
            continue
        location = _storage_class_excerpt(document, class_name)
        if location is None:
            continue
        locator, excerpt = location
        seen.add(tier_code)
        candidates.append(
            ObsStorageClassCandidate(
                official_name=class_name,
                tier_code=tier_code,
                excerpt=excerpt,
                locator=locator,
            )
        )
    return candidates


def _storage_class_excerpt(
    document: HtmlDocument,
    class_name: str,
) -> tuple[str, str] | None:
    paragraphs = document.paragraphs_containing(class_name)
    for locator, paragraph in paragraphs:
        if any(
            keyword in paragraph for keyword in ("适用场景", "规格限制", "最低存储时间", "数据恢复")
        ):
            return locator, paragraph
    text = document.text
    for match_index, match in enumerate(re.finditer(re.escape(class_name), text)):
        excerpt = text[match.start() : match.start() + 900]
        if any(
            keyword in excerpt for keyword in ("适用场景", "规格限制", "最低存储时间", "数据恢复")
        ):
            return f"html:text:storage_class[{match_index}]", excerpt
    if paragraphs:
        return paragraphs[0]
    return None


def _storage_class_fields(storage_class: ObsStorageClassCandidate) -> list[FieldCandidate]:
    fields = [
        _candidate(
            field_code="obs.storage_class.official_name",
            raw_value=storage_class.official_name,
            raw_unit=None,
            normalized_value=storage_class.official_name,
            canonical_unit=None,
            locator=storage_class.locator,
            excerpt=storage_class.excerpt,
            parser_rule="obs.storage_class.name",
            target_table="service_tier",
            target_identity=storage_class.tier_code,
            confidence=0.88,
            section_title="OBS storage class",
        )
    ]
    minimum_days = _minimum_days_from_text(storage_class.excerpt)
    if minimum_days:
        fields.append(
            _candidate(
                field_code="object_storage.minimum_storage_duration_days",
                raw_value=minimum_days[0],
                raw_unit="day",
                normalized_value=minimum_days[1],
                canonical_unit="day",
                locator=storage_class.locator,
                excerpt=storage_class.excerpt,
                parser_rule="obs.storage_class.minimum_days",
                target_table="service_tier",
                target_identity=storage_class.tier_code,
                confidence=0.82,
                section_title="OBS storage class",
            )
        )
    retrieval = _retrieval_description_from_text(storage_class.excerpt)
    if retrieval:
        fields.append(
            _candidate(
                field_code="object_storage.retrieval_time_description",
                raw_value=retrieval,
                raw_unit=None,
                normalized_value=retrieval,
                canonical_unit=None,
                locator=storage_class.locator,
                excerpt=storage_class.excerpt,
                parser_rule="obs.storage_class.retrieval_description",
                target_table="service_tier",
                target_identity=storage_class.tier_code,
                confidence=0.78,
                section_title="OBS storage class",
            )
        )
    for field_code, keyword, rule in (
        (
            "object_storage.durability_percentage",
            "持久性",
            "obs.storage_class.design_durability",
        ),
        (
            "object_storage.availability_percentage",
            "可用性",
            "obs.storage_class.design_availability",
        ),
    ):
        value = _percentage_near_keyword(storage_class.excerpt, keyword)
        if value is None:
            continue
        fields.append(
            _candidate(
                field_code=field_code,
                raw_value=value,
                raw_unit="percent",
                normalized_value=normalize_percentage(value),
                canonical_unit="percent",
                locator=storage_class.locator,
                excerpt=storage_class.excerpt,
                parser_rule=rule,
                target_table="service_tier",
                target_identity=storage_class.tier_code,
                confidence=0.8,
                section_title="OBS storage class",
            )
        )
    return fields


def _capability_fields(document: HtmlDocument) -> list[FieldCandidate]:
    rules = (
        ("object_storage.versioning_supported", "多版本", "obs.capability.versioning"),
        ("object_storage.lifecycle_management_supported", "生命周期", "obs.capability.lifecycle"),
        ("object_storage.cross_region_replication_supported", "跨区域复制", "obs.capability.crr"),
        ("object_storage.server_side_encryption_supported", "加密", "obs.capability.encryption"),
        ("object_storage.multipart_upload_supported", "分段上传", "obs.capability.multipart"),
        ("object_storage.static_website_hosting_supported", "静态网站", "obs.capability.website"),
        ("object_storage.event_notification_supported", "事件通知", "obs.capability.notification"),
        ("object_storage.object_lock_supported", "对象锁", "obs.capability.object_lock"),
    )
    fields: list[FieldCandidate] = []
    for field_code, keyword, rule in rules:
        paragraphs = document.paragraphs_containing(keyword)
        if not paragraphs:
            continue
        locator, excerpt = paragraphs[0]
        fields.append(
            _candidate(
                field_code=field_code,
                raw_value="支持",
                raw_unit=None,
                normalized_value=True,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule=rule,
                target_table="product_specification",
                target_identity="obs",
                confidence=0.8,
                section_title="OBS capability",
            )
        )
    for field_code, keyword, rule in (
        ("object_storage.durability_percentage", "持久性", "obs.metric.durability"),
        ("object_storage.availability_percentage", "可用性", "obs.metric.availability"),
    ):
        for locator, excerpt in document.paragraphs_containing(keyword):
            value = _percentage_from_text(excerpt)
            if value is None:
                continue
            fields.append(
                _candidate(
                    field_code=field_code,
                    raw_value=value,
                    raw_unit="percent",
                    normalized_value=normalize_percentage(value),
                    canonical_unit="percent",
                    locator=locator,
                    excerpt=excerpt,
                    parser_rule=rule,
                    target_table="product_specification",
                    target_identity="obs",
                    confidence=0.82,
                    section_title="OBS metric",
                )
            )
            break
    return fields


def _minimum_days_from_text(text: str) -> tuple[str, int] | None:
    match = re.search(r"(\d+)\s*天", text)
    if not match:
        return None
    normalized, _unit = normalize_days(match.group(1))
    return (match.group(0), normalized) if normalized is not None else None


def _retrieval_description_from_text(text: str) -> str | None:
    match = re.search(
        r"(实时访问|标准恢复[:：]?\s*\d+~\d+\s*h|加急恢复[:：]?\s*\d+~\d+\s*(?:min|h))", text
    )
    return match.group(0) if match else None


def _percentage_near_keyword(text: str, keyword: str) -> str | None:
    keyword_index = text.find(keyword)
    if keyword_index < 0:
        return None
    excerpt = text[keyword_index : keyword_index + 160]
    return _percentage_from_text(excerpt)


def _parse_sla_fields(
    document: HtmlDocument,
    source_id: str,
) -> list[tuple[str, list[FieldCandidate]]]:
    if not source_id.endswith("_sla"):
        return []
    patterns = (
        (
            "obs_standard_single_az",
            "standard single-AZ availability",
            r"(标准存储\s*单\s*可用区[^。；;]*?不低于\s*(\d+(?:\.\d+)?%))",
        ),
        (
            "obs_standard_multi_az",
            "standard multi-AZ availability",
            r"(标准存储\s*三\s*可用区[^。；;]*?不低于\s*(\d+(?:\.\d+)?%))",
        ),
        (
            "obs_infrequent_access_single_az",
            "infrequent access single-AZ availability",
            r"(低频\s*访问存储\s*单\s*可用区[^。；;]*?不低于\s*(\d+(?:\.\d+)?%))",
        ),
        (
            "obs_infrequent_access_multi_az",
            "infrequent access multi-AZ availability",
            r"(低频\s*访问存储\s*三\s*可用区[^。；;]*?不低于\s*(\d+(?:\.\d+)?%))",
        ),
        (
            "obs_archive",
            "archive availability",
            r"(归档存储[^。；;]*?不低于\s*(\d+(?:\.\d+)?%))",
        ),
    )
    results: list[tuple[str, list[FieldCandidate]]] = []
    for scope, section_title, pattern in patterns:
        match = re.search(pattern, document.text)
        if not match:
            continue
        excerpt = match.group(1)
        raw_value = match.group(2)
        results.append(
            (
                scope,
                [
                    _candidate(
                        field_code="sla.availability_percentage",
                        raw_value=raw_value,
                        raw_unit="percent",
                        normalized_value=normalize_percentage(raw_value),
                        canonical_unit="percent",
                        locator=f"html:text:sla:{scope}",
                        excerpt=excerpt,
                        parser_rule="obs.sla.availability_commitment",
                        target_table="product_sla",
                        target_identity=scope,
                        confidence=0.86,
                        section_title=section_title,
                    )
                ],
            )
        )
    return results


def _percentage_from_text(text: str) -> str | None:
    match = re.search(r"\d+(?:\.\d+)?\s*%", text)
    return match.group(0) if match else None


def _excerpt_around(text: str, keyword: str, radius: int = 120) -> str:
    index = text.find(keyword)
    if index < 0:
        return text[:radius]
    start = max(index - radius // 2, 0)
    end = min(index + radius, len(text))
    return text[start:end]
