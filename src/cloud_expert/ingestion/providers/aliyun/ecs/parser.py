import re
from decimal import Decimal

from cloud_expert.database.enums import AvailabilityStatus, ReviewStatus
from cloud_expert.ingestion.providers.aliyun.common import (
    ALIYUN_PUBLIC_CN_PARTITION,
    is_mainland_region_code,
)
from cloud_expert.normalization.percentages import normalize_percentage
from cloud_expert.normalization.units import (
    normalize_memory_to_gib,
    parse_decimal,
)
from cloud_expert.parsing.html_adapter import HtmlDocument, HtmlTable
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord

PARSER_VERSION = "2026.09.c09_aliyun_ecs_table_units_v2"
INSTANCE_TYPE_PATTERN = re.compile(r"\becs\.[a-z0-9-]+(?:\.[a-z0-9.-]+)?\b", re.IGNORECASE)
REGION_CODE_PATTERN = re.compile(r"\bcn-[a-z0-9-]+(?:-[a-z0-9]+)*\b")
ZONE_CODE_PATTERN = re.compile(r"\b(cn-[a-z0-9-]+-[a-z])\b")


def parse_ecs_document(
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
                target_identity="ecs",
                fields=product_fields,
                parser_version=PARSER_VERSION,
            )
        )
    records.extend(_instance_records(document, source_id, snapshot_id))
    records.extend(_region_zone_records(document, source_id, snapshot_id))
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
    official_name = "云服务器 ECS"
    fields = [
        _candidate(
            field_code="product.official_name",
            raw_value=official_name,
            raw_unit=None,
            normalized_value=official_name,
            canonical_unit=None,
            locator="html:h1",
            excerpt=heading or official_name,
            parser_rule="aliyun.ecs.product.official_name",
            target_table="product",
            target_identity="ecs",
            confidence=0.9,
            section_title="product heading",
        )
    ]
    description = document.product_description_containing(
        "云服务器 ECS", "Elastic Compute Service", "ECS"
    )
    if description:
        locator, excerpt = description
        fields.append(
            _candidate(
                field_code="product.description",
                raw_value=excerpt,
                raw_unit=None,
                normalized_value=excerpt,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.product.description",
                target_table="product",
                target_identity="ecs",
                confidence=0.84,
                section_title="product description",
            )
        )
    return fields


def _instance_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    if not any(token in source_id for token in ("instance", "describe_instance_types")):
        return []
    records: list[ParsedRecord] = []
    seen_families: set[str] = set()
    for table in document.tables():
        header_map = _header_map(table)
        instance_index = header_map.get("instance")
        if instance_index is None:
            continue
        for row_index, row in enumerate(table.rows):
            instance_type = _first_instance_type(_cell(row, instance_index) or "")
            if not instance_type:
                continue
            excerpt = " | ".join(row)
            locator = f"{table.locator}:row[{row_index}]"
            family_code = _aliyun_family_code(instance_type)
            if family_code and family_code not in seen_families:
                seen_families.add(family_code)
                records.append(
                    ParsedRecord(
                        record_type="aliyun_ecs_instance_family",
                        source_id=source_id,
                        snapshot_id=snapshot_id,
                        target_identity=family_code,
                        fields=_family_fields(family_code, locator, excerpt),
                        parser_version=PARSER_VERSION,
                    )
                )
            fields = _sku_fields(row, header_map, instance_type, locator, excerpt, table.headers)
            if fields:
                records.append(
                    ParsedRecord(
                        record_type="aliyun_ecs_sku",
                        source_id=source_id,
                        snapshot_id=snapshot_id,
                        target_identity=instance_type,
                        fields=fields,
                        parser_version=PARSER_VERSION,
                    )
                )
    if records:
        return records[:1200]
    return _instance_records_from_text(document, source_id, snapshot_id)


def _instance_records_from_text(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    records: list[ParsedRecord] = []
    seen: set[str] = set()
    seen_families: set[str] = set()
    for match in INSTANCE_TYPE_PATTERN.finditer(document.text):
        instance_type = match.group(0)
        if instance_type.count(".") < 2 or instance_type in seen:
            continue
        seen.add(instance_type)
        excerpt = document.text[max(match.start() - 160, 0) : match.start() + 640]
        locator = f"html:text:instance_type[{len(seen)}]"
        family_code = _aliyun_family_code(instance_type)
        if family_code and family_code not in seen_families:
            seen_families.add(family_code)
            records.append(
                ParsedRecord(
                    record_type="aliyun_ecs_instance_family",
                    source_id=source_id,
                    snapshot_id=snapshot_id,
                    target_identity=family_code,
                    fields=_family_fields(family_code, locator, excerpt),
                    parser_version=PARSER_VERSION,
                )
            )
        records.append(
            ParsedRecord(
                record_type="aliyun_ecs_sku",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity=instance_type,
                fields=[
                    _candidate(
                        field_code="sku.provider_sku_code",
                        raw_value=instance_type,
                        raw_unit=None,
                        normalized_value=instance_type,
                        canonical_unit=None,
                        locator=locator,
                        excerpt=excerpt,
                        parser_rule="aliyun.ecs.sku.instance_type.from_text",
                        target_table="sku",
                        target_identity=instance_type,
                        confidence=0.72,
                        section_title="ECS instance text",
                    )
                ],
                parser_version=PARSER_VERSION,
            )
        )
    return records[:600]


def _family_fields(family_code: str, locator: str, excerpt: str) -> list[FieldCandidate]:
    return [
        _candidate(
            field_code="ecs.instance_family",
            raw_value=family_code,
            raw_unit=None,
            normalized_value=family_code,
            canonical_unit=None,
            locator=locator,
            excerpt=excerpt,
            parser_rule="aliyun.ecs.family.from_instance_type",
            target_table="product_family",
            target_identity=family_code,
            confidence=0.82,
            section_title="ECS instance family",
        )
    ]


def _sku_fields(
    row: list[str],
    header_map: dict[str, int],
    instance_type: str,
    locator: str,
    excerpt: str,
    headers: list[str],
) -> list[FieldCandidate]:
    fields = [
        _candidate(
            field_code="sku.provider_sku_code",
            raw_value=instance_type,
            raw_unit=None,
            normalized_value=instance_type,
            canonical_unit=None,
            locator=locator,
            excerpt=excerpt,
            parser_rule="aliyun.ecs.sku.instance_type",
            target_table="sku",
            target_identity=instance_type,
            confidence=0.93,
            section_title="ECS instance table",
        )
    ]
    # The shared HTML adapter does not expand merged cells; never shift numeric columns.
    if len(row) != len(headers):
        return fields
    _add_decimal_field(
        fields,
        row,
        header_map,
        key="vcpu",
        field_code="compute.vcpu_count",
        unit="count",
        canonical_unit="count",
        parser_rule="aliyun.ecs.sku.vcpu",
        target_identity=instance_type,
        locator=locator,
        excerpt=excerpt,
    )
    memory = _cell(row, header_map.get("memory"))
    if memory:
        value, unit = normalize_memory_to_gib(memory)
        fields.append(
            _candidate(
                field_code="compute.memory_gib",
                raw_value=memory,
                raw_unit="GiB",
                normalized_value=value,
                canonical_unit=unit,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.sku.memory",
                target_table="sku",
                target_identity=instance_type,
                confidence=0.9 if value is not None else 0.62,
                section_title="ECS instance table",
            )
        )
    processor = _cell(row, header_map.get("processor"))
    if processor:
        fields.extend(_processor_fields(processor, locator, excerpt, instance_type))
    for key in _PERFORMANCE_FIELDS:
        index = header_map.get(key)
        raw_value = _cell(row, index)
        if raw_value is not None and index is not None:
            fields.extend(
                _performance_fields(
                    key,
                    raw_value,
                    headers[index],
                    f"{locator}:cell[{index}]",
                    excerpt,
                    instance_type,
                )
            )
    local_storage = _cell(row, header_map.get("local_storage"))
    if local_storage:
        fields.extend(_local_storage_fields(local_storage, locator, excerpt, instance_type))
    gpu = _cell(row, header_map.get("gpu"))
    if gpu:
        fields.extend(_gpu_fields(gpu, locator, excerpt, instance_type))
    return fields


def _processor_fields(
    raw_value: str,
    locator: str,
    excerpt: str,
    target_identity: str,
) -> list[FieldCandidate]:
    fields = [
        _candidate(
            field_code="compute.processor_model",
            raw_value=raw_value,
            raw_unit=None,
            normalized_value=raw_value,
            canonical_unit=None,
            locator=locator,
            excerpt=excerpt,
            parser_rule="aliyun.ecs.sku.processor_model",
            target_table="sku",
            target_identity=target_identity,
            confidence=0.84,
            section_title="ECS instance table",
        )
    ]
    vendor = _processor_vendor(raw_value)
    if vendor:
        fields.append(
            _candidate(
                field_code="compute.processor_vendor",
                raw_value=vendor,
                raw_unit=None,
                normalized_value=vendor,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.sku.processor_vendor",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.82,
                section_title="ECS instance table",
            )
        )
    architecture = _architecture(raw_value)
    if architecture:
        fields.append(
            _candidate(
                field_code="compute.cpu_architecture",
                raw_value=raw_value,
                raw_unit=None,
                normalized_value=architecture,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.sku.cpu_architecture",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.78,
                section_title="ECS instance table",
            )
        )
    return fields


_PERFORMANCE_FIELDS = {
    "network": ("network.baseline_bandwidth_gbps", "network.max_bandwidth_gbps", "Gbps"),
    "pps": ("network.baseline_pps", "network.max_pps", "PPS"),
    "connections": ("network.baseline_connections", "network.max_connections", "count"),
    "cloud_disk_bandwidth": (
        "network.cloud_disk_baseline_bandwidth_gbps",
        "network.cloud_disk_bandwidth_gbps",
        "Gbps",
    ),
    "cloud_disk_iops": ("storage.cloud_disk_baseline_iops", "storage.cloud_disk_iops", "IOPS"),
}
_QUALIFIER = re.compile(
    r"基础|基准|最高|最大|突发|\bbaseline\b|\bmaximum\b|\bmax\b|\bup\s+to\b|\bburst\b", re.I
)
_NUMBER = r"(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?"
_BANDWIDTH_UNIT = r"[KMGkmg](?:bit/s|bps|[bB]/s)"
_MAGNITUDES = {
    "万": Decimal(10000),
    "亿": Decimal(100000000),
    "k": Decimal(1000),
    "m": Decimal(1000000),
}


def _qualifiers(value: str) -> list[str]:
    return [
        "baseline" if match.group().lower() in {"基础", "基准", "baseline"} else "maximum"
        for match in _QUALIFIER.finditer(value)
    ]


def _performance_parts(raw_value: str, header: str, default: str) -> list[tuple[str, str | None]]:
    # Unit slashes (Gbit/s, GB/s) are not baseline/burst separators.
    parts = re.split(r"[/／](?!s\b)", raw_value, flags=re.I)
    header_qualifiers = list(dict.fromkeys(_qualifiers(header)))
    result: list[tuple[str, str | None]] = []
    for index, part in enumerate(parts):
        qualifiers = list(dict.fromkeys(_qualifiers(part)))
        if len(qualifiers) == 1:
            qualifier = qualifiers[0]
        elif not qualifiers and len(header_qualifiers) == len(parts):
            qualifier = header_qualifiers[index]
        elif not qualifiers and len(parts) == 1:
            qualifier = header_qualifiers[0] if header_qualifiers else default
        else:
            return [(default, None)]
        result.append((qualifier, part))
    if len(parts) > 2 or len({qualifier for qualifier, _ in result}) != len(result):
        return [(default, None)]
    return result


def _table_number(raw_value: str, header: str, unit: str) -> Decimal | None:
    text = _QUALIFIER.sub("", raw_value).strip(" :：")
    if unit == "Gbps":
        match = re.fullmatch(rf"({_NUMBER})\s*({_BANDWIDTH_UNIT})?", text)
        if match is None:
            return None
        header_unit = re.search(_BANDWIDTH_UNIT, header)
        source_unit = match[2] or (header_unit[0] if header_unit else "Gbps")
        multiplier = {"k": Decimal("0.000001"), "m": Decimal("0.001"), "g": Decimal(1)}[
            source_unit[0].lower()
        ]
        if "B/s" in source_unit:
            multiplier *= 8
    else:
        suffix = {"PPS": "pps", "IOPS": "iops", "count": "count|个|条"}[unit]
        match = re.fullmatch(rf"({_NUMBER})\s*([万亿kKmM])?\s*({suffix})?", text, re.I)
        if match is None:
            return None
        magnitude = match[2]
        # Explicit cell magnitudes/units override header units, never multiply twice.
        if magnitude is None and match[3] is None:
            header_magnitude = re.search(r"[万亿]|\b([kKmM])(?:pps|iops)\b", header, re.I)
            if header_magnitude:
                magnitude = header_magnitude[1] or header_magnitude[0]
        multiplier = _MAGNITUDES.get((magnitude or "").lower(), Decimal(1))
    return Decimal(match[1].replace(",", "").replace("，", "")) * multiplier


def _performance_fields(
    key: str,
    raw_value: str,
    header: str,
    locator: str,
    excerpt: str,
    target_identity: str,
) -> list[FieldCandidate]:
    baseline_code, maximum_code, unit = _PERFORMANCE_FIELDS[key]
    default = "baseline" if key == "network" else "maximum"
    fields = []
    for qualifier, part in _performance_parts(raw_value, header, default):
        fields.append(
            _numeric_text_field(
                baseline_code if qualifier == "baseline" else maximum_code,
                raw_value,
                _table_number(part, header, unit) if part is not None else None,
                unit,
                locator,
                f"{header}: {raw_value} | {excerpt}",
                target_identity,
                f"aliyun.ecs.sku.{key}.table_units_v2.{qualifier}",
            )
        )
    return fields


def _local_storage_fields(
    raw_value: str,
    locator: str,
    excerpt: str,
    target_identity: str,
) -> list[FieldCandidate]:
    fields: list[FieldCandidate] = []
    match = re.search(
        r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*([TGMK]i?B|TB|GB)", raw_value, re.IGNORECASE
    )
    if match:
        fields.append(
            _numeric_text_field(
                "storage.local_disk_count",
                raw_value,
                Decimal(match.group(1)),
                "count",
                locator,
                excerpt,
                target_identity,
                "aliyun.ecs.sku.local_disk_count",
            )
        )
        capacity, unit = normalize_memory_to_gib(f"{match.group(2)} {match.group(3)}")
        fields.append(
            _numeric_text_field(
                "storage.local_disk_capacity_gib",
                raw_value,
                capacity,
                unit,
                locator,
                excerpt,
                target_identity,
                "aliyun.ecs.sku.local_disk_capacity",
            )
        )
    storage_type = re.search(r"(NVMe\s*SSD|SSD|HDD|本地SSD)", raw_value, re.IGNORECASE)
    if storage_type:
        fields.append(
            _candidate(
                field_code="storage.local_disk_type",
                raw_value=storage_type.group(1),
                raw_unit=None,
                normalized_value=storage_type.group(1),
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.sku.local_disk_type",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.82,
                section_title="ECS storage table",
            )
        )
    return fields


def _gpu_fields(
    raw_value: str,
    locator: str,
    excerpt: str,
    target_identity: str,
) -> list[FieldCandidate]:
    fields: list[FieldCandidate] = []
    count = parse_decimal(raw_value)
    if count is not None:
        fields.append(
            _numeric_text_field(
                "gpu.count",
                raw_value,
                count,
                "count",
                locator,
                excerpt,
                target_identity,
                "aliyun.ecs.sku.gpu_count",
            )
        )
    model = re.search(
        r"(NVIDIA|A10|A100|T4|V100|L20|H20|Intel GPU)[^,，；;|]*", raw_value, re.IGNORECASE
    )
    if model:
        fields.append(
            _candidate(
                field_code="gpu.model",
                raw_value=model.group(0),
                raw_unit=None,
                normalized_value=model.group(0),
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.sku.gpu_model",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.74,
                section_title="ECS accelerator table",
            )
        )
    return fields


def _region_zone_records(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    if "regions" not in source_id and "zones" not in source_id:
        return []
    records = _zone_records_from_tables(document, source_id, snapshot_id)
    if records:
        return records
    return _zone_records_from_text(document, source_id, snapshot_id)


def _zone_records_from_tables(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    records: list[ParsedRecord] = []
    seen_regions: set[str] = set()
    seen_zones: set[str] = set()
    current_region_code: str | None = None
    current_region_name: str | None = None
    for table in document.tables():
        header_map = _region_zone_header_map(table)
        region_code_index = header_map.get("region_code")
        zone_code_index = header_map.get("zone_code")
        if region_code_index is None and zone_code_index is None:
            continue
        for row_index, row in enumerate(table.rows):
            region_code = _cell(row, region_code_index)
            if region_code and is_mainland_region_code(region_code):
                current_region_code = region_code
                current_region_name = _cell(row, header_map.get("region_name")) or region_code
            zone_code = _cell(row, zone_code_index)
            if not zone_code:
                zone_code = _first_zone_code(" | ".join(row))
            if current_region_code is None or not zone_code or zone_code in seen_zones:
                continue
            if not is_mainland_region_code(_region_from_zone(zone_code)):
                continue
            zone_name = _zone_name_from_row(row, zone_code, header_map) or zone_code
            excerpt = " | ".join(row)
            locator = f"{table.locator}:row[{row_index}]"
            if current_region_code not in seen_regions:
                seen_regions.add(current_region_code)
                records.append(
                    _region_record(
                        source_id,
                        snapshot_id,
                        current_region_code,
                        current_region_name or current_region_code,
                        locator,
                        excerpt,
                    )
                )
            seen_zones.add(zone_code)
            records.append(
                _zone_record(
                    source_id,
                    snapshot_id,
                    current_region_code,
                    current_region_name or current_region_code,
                    zone_code,
                    zone_name,
                    locator,
                    excerpt,
                )
            )
    return records


def _zone_records_from_text(
    document: HtmlDocument,
    source_id: str,
    snapshot_id: str,
) -> list[ParsedRecord]:
    records: list[ParsedRecord] = []
    seen_regions: set[str] = set()
    seen_zones: set[str] = set()
    text = _domestic_region_text(document.text)
    for match in ZONE_CODE_PATTERN.finditer(text):
        zone_code = match.group(1)
        region_code = _region_from_zone(zone_code)
        if not is_mainland_region_code(region_code) or zone_code in seen_zones:
            continue
        excerpt = text[max(match.start() - 180, 0) : match.start() + 360]
        zone_name = _zone_name_from_excerpt(excerpt, zone_code)
        region_name = _region_name_from_excerpt(excerpt, region_code)
        locator = f"html:text:zone[{len(seen_zones)}]"
        if region_code not in seen_regions:
            seen_regions.add(region_code)
            records.append(
                _region_record(
                    source_id,
                    snapshot_id,
                    region_code,
                    region_name or region_code,
                    locator,
                    excerpt,
                )
            )
        seen_zones.add(zone_code)
        records.append(
            _zone_record(
                source_id,
                snapshot_id,
                region_code,
                region_name or region_code,
                zone_code,
                zone_name or zone_code,
                locator,
                excerpt,
            )
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
                parser_rule="aliyun.ecs.region.partition",
                target_table="availability",
                target_identity=region_code,
                confidence=0.9,
                section_title="ECS regions and zones",
            ),
            _candidate(
                field_code="region.code",
                raw_value=region_code,
                raw_unit=None,
                normalized_value=region_code,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.region.code",
                target_table="availability",
                target_identity=region_code,
                confidence=0.9,
                section_title="ECS regions and zones",
            ),
            _candidate(
                field_code="region.name",
                raw_value=region_name,
                raw_unit=None,
                normalized_value=region_name,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.region.name",
                target_table="availability",
                target_identity=region_code,
                confidence=0.82,
                section_title="ECS regions and zones",
            ),
            _candidate(
                field_code="availability.status",
                raw_value=AvailabilityStatus.AVAILABLE.value,
                raw_unit=None,
                normalized_value=AvailabilityStatus.AVAILABLE.value,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.region.available",
                target_table="availability",
                target_identity=region_code,
                confidence=0.82,
                section_title="ECS regions and zones",
            ),
        ],
        parser_version=PARSER_VERSION,
    )


def _zone_record(
    source_id: str,
    snapshot_id: str,
    region_code: str,
    region_name: str,
    zone_code: str,
    zone_name: str,
    locator: str,
    excerpt: str,
) -> ParsedRecord:
    del region_name
    return ParsedRecord(
        record_type="zone_availability",
        source_id=source_id,
        snapshot_id=snapshot_id,
        target_identity=zone_code,
        fields=[
            _candidate(
                field_code="cloud.partition",
                raw_value=ALIYUN_PUBLIC_CN_PARTITION,
                raw_unit=None,
                normalized_value=ALIYUN_PUBLIC_CN_PARTITION,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.zone.partition",
                target_table="zone_availability",
                target_identity=zone_code,
                confidence=0.9,
                section_title="ECS regions and zones",
            ),
            _candidate(
                field_code="region.code",
                raw_value=region_code,
                raw_unit=None,
                normalized_value=region_code,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.zone.region_code",
                target_table="zone_availability",
                target_identity=zone_code,
                confidence=0.9,
                section_title="ECS regions and zones",
            ),
            _candidate(
                field_code="zone.code",
                raw_value=zone_code,
                raw_unit=None,
                normalized_value=zone_code,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.zone.code",
                target_table="zone_availability",
                target_identity=zone_code,
                confidence=0.9,
                section_title="ECS regions and zones",
            ),
            _candidate(
                field_code="zone.name",
                raw_value=zone_name,
                raw_unit=None,
                normalized_value=zone_name,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.zone.name",
                target_table="zone_availability",
                target_identity=zone_code,
                confidence=0.78,
                section_title="ECS regions and zones",
            ),
            _candidate(
                field_code="availability.status",
                raw_value=AvailabilityStatus.AVAILABLE.value,
                raw_unit=None,
                normalized_value=AvailabilityStatus.AVAILABLE.value,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aliyun.ecs.zone.available",
                target_table="zone_availability",
                target_identity=zone_code,
                confidence=0.82,
                section_title="ECS regions and zones",
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
    patterns = (
        ("ecs_single_instance", "单实例", r"单实例[^。；;]{0,80}?不低于\s*(\d+(?:\.\d+)?%)"),
        (
            "ecs_multi_zone",
            "单地域多可用区",
            r"单地域多可用区[^。；;]{0,80}?不低于\s*(\d+(?:\.\d+)?%)",
        ),
    )
    records: list[ParsedRecord] = []
    for scope, label, pattern in patterns:
        match = re.search(pattern, document.text)
        if not match:
            continue
        raw_value = match.group(1)
        excerpt = document.text[max(match.start() - 100, 0) : match.end() + 260]
        records.append(
            ParsedRecord(
                record_type="product_sla",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity=scope,
                fields=[
                    _candidate(
                        field_code="sla.availability_percentage",
                        raw_value=raw_value,
                        raw_unit="percent",
                        normalized_value=normalize_percentage(raw_value),
                        canonical_unit="percent",
                        locator=f"html:text:sla:{scope}",
                        excerpt=excerpt,
                        parser_rule="aliyun.ecs.sla.availability_commitment",
                        target_table="product_sla",
                        target_identity=scope,
                        confidence=0.86,
                        section_title=label,
                    )
                ],
                parser_version=PARSER_VERSION,
            )
        )
    return records


def _header_map(table: HtmlTable) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(table.headers):
        normalized = _normalize_header(header)
        if "实例规格" in header or "instancetype" in normalized:
            mapping["instance"] = index
        elif "vcpu" in normalized or "vCPU" in header or header.strip() == "核":
            mapping["vcpu"] = index
        elif ("内存" in header or "memory" in normalized) and not any(
            token in normalized for token in ("持久", "加密", "persistent", "encrypted", "gpu")
        ):
            mapping["memory"] = index
        elif "处理器" in header or "processor" in normalized or normalized == "cpu":
            mapping["processor"] = index
        elif "pps" in normalized or "收发包" in header:
            mapping["pps"] = index
        elif "连接" in header:
            mapping["connections"] = index
        elif "云盘" in header and ("带宽" in header or "吞吐" in header):
            mapping["cloud_disk_bandwidth"] = index
        elif "iops" in normalized and "云盘" in header:
            mapping["cloud_disk_iops"] = index
        elif (
            "网络" in header
            and "包" not in header
            and not any(token in normalized for token in ("rdma", "roce"))
        ):
            mapping["network"] = index
        elif "本地" in header or "存储" in header:
            mapping["local_storage"] = index
        elif ("GPU" in header or "NPU" in header) and "显存" not in header:
            mapping["gpu"] = index
    return mapping


def _region_zone_header_map(table: HtmlTable) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(table.headers):
        normalized = _normalize_header(header)
        if "地域id" in normalized or "regionid" in normalized:
            mapping["region_code"] = index
        elif "地域名称" in header or "regionname" in normalized:
            mapping["region_name"] = index
        elif "可用区id" in normalized or "zoneid" in normalized:
            mapping["zone_code"] = index
        elif "可用区名称" in header or "zonename" in normalized:
            mapping["zone_name"] = index
    return mapping


def _add_decimal_field(
    fields: list[FieldCandidate],
    row: list[str],
    header_map: dict[str, int],
    *,
    key: str,
    field_code: str,
    unit: str,
    canonical_unit: str,
    parser_rule: str,
    target_identity: str,
    locator: str,
    excerpt: str,
) -> None:
    raw_value = _cell(row, header_map.get(key))
    if not raw_value:
        return
    value = parse_decimal(raw_value)
    fields.append(
        _numeric_text_field(
            field_code,
            raw_value,
            value,
            canonical_unit or unit,
            locator,
            excerpt,
            target_identity,
            parser_rule,
        )
    )


def _numeric_text_field(
    field_code: str,
    raw_value: object,
    normalized_value: object,
    canonical_unit: str | None,
    locator: str,
    excerpt: str,
    target_identity: str,
    parser_rule: str,
) -> FieldCandidate:
    return _candidate(
        field_code=field_code,
        raw_value=raw_value,
        raw_unit=canonical_unit,
        normalized_value=normalized_value,
        canonical_unit=canonical_unit,
        locator=locator,
        excerpt=excerpt,
        parser_rule=parser_rule,
        target_table="sku",
        target_identity=target_identity,
        confidence=0.84 if normalized_value is not None else 0.62,
        section_title="ECS instance table",
    )


def _normalize_header(value: str) -> str:
    return re.sub(r"[\s/_:：()（）-]+", "", value.lower())


def _cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    value = " ".join(row[index].split())
    return value or None


def _first_instance_type(value: str) -> str | None:
    match = INSTANCE_TYPE_PATTERN.search(value)
    return match.group(0) if match else None


def _first_zone_code(value: str) -> str | None:
    match = ZONE_CODE_PATTERN.search(value)
    return match.group(1) if match else None


def _zone_name_from_row(
    row: list[str],
    zone_code: str,
    header_map: dict[str, int],
) -> str | None:
    named_cell = _cell(row, header_map.get("zone_name"))
    if named_cell and named_cell != zone_code and not ZONE_CODE_PATTERN.fullmatch(named_cell):
        return named_cell
    for cell in row:
        value = " ".join(cell.split())
        if not value or value == zone_code:
            continue
        if ZONE_CODE_PATTERN.fullmatch(value):
            continue
        if "可用区" in value or "Zone" in value or "zone" in value.lower():
            return value
    return None


def _aliyun_family_code(instance_type: str) -> str:
    tokens = instance_type.split(".")
    if len(tokens) >= 2 and tokens[0] == "ecs":
        return tokens[1]
    return tokens[0]


def _region_from_zone(zone_code: str) -> str:
    return zone_code.rsplit("-", 1)[0]


def _domestic_region_text(text: str) -> str:
    start_markers = ("中国地区", "亚太-中国", "地域名称 地域 ID")
    start = 0
    for marker in start_markers:
        index = text.find(marker)
        if index >= 0:
            start = index
            break
    end = text.find("其他国家和地区", start)
    if end < 0:
        end = len(text)
    return text[start:end]


def _zone_name_from_excerpt(excerpt: str, zone_code: str) -> str | None:
    index = excerpt.find(zone_code)
    if index <= 0:
        return None
    before = excerpt[max(0, index - 80) : index]
    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9（）() -]+可用区\s*[A-Z])\s*$", before)
    return " ".join(match.group(1).split()) if match else None


def _region_name_from_excerpt(excerpt: str, region_code: str) -> str | None:
    index = excerpt.find(region_code)
    if index <= 0:
        return None
    before = excerpt[max(0, index - 80) : index]
    candidates = re.findall(r"([\u4e00-\u9fff]+\s*\d?（[^）]+）|[\u4e00-\u9fff]+)", before)
    return candidates[-1].strip() if candidates else None


def _processor_vendor(value: str) -> str | None:
    lowered = value.lower()
    if "intel" in lowered or "xeon" in lowered:
        return "Intel"
    if "amd" in lowered or "epyc" in lowered:
        return "AMD"
    if "海光" in value:
        return "Hygon"
    if "倚天" in value or "yitian" in lowered:
        return "Alibaba Yitian"
    if "ampere" in lowered:
        return "Ampere"
    return None


def _architecture(value: str) -> str | None:
    lowered = value.lower()
    if "arm" in lowered or "倚天" in value or "ampere" in lowered:
        return "arm64"
    if any(token in lowered for token in ("intel", "xeon", "amd", "epyc")) or "海光" in value:
        return "x86_64"
    return None
