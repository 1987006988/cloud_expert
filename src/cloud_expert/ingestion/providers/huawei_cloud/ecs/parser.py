import re
from decimal import Decimal

from cloud_expert.database.enums import ReviewStatus
from cloud_expert.ingestion.providers.huawei_cloud.common import PARSER_VERSION
from cloud_expert.ingestion.providers.huawei_cloud.ecs.schemas import EcsSkuParsedRow
from cloud_expert.normalization.ecs import infer_ecs_architecture_from_text, infer_ecs_family_code
from cloud_expert.normalization.percentages import normalize_percentage
from cloud_expert.normalization.units import (
    normalize_bandwidth_to_gbps,
    normalize_memory_to_gib,
    parse_decimal,
)
from cloud_expert.parsing.html_adapter import HtmlDocument, HtmlTable
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord


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
    family_fields = _parse_family_fields(document)
    for family_code, fields in family_fields:
        records.append(
            ParsedRecord(
                record_type="ecs_instance_family",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity=family_code,
                fields=fields,
                parser_version=PARSER_VERSION,
            )
        )
    for sku_row in _parse_sku_rows(document):
        records.append(
            ParsedRecord(
                record_type="ecs_sku",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity=sku_row.provider_sku_code,
                fields=_sku_fields(sku_row),
                parser_version=PARSER_VERSION,
            )
        )
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
        "弹性云服务器 ECS"
        if "弹性云服务器" in document.text or "Elastic Cloud Server" in document.text
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
            else _excerpt_around(document.text, "弹性云服务器"),
            parser_rule="ecs.product.heading",
            target_table="product",
            target_identity="ecs",
            confidence=0.9,
            section_title="product heading",
        )
    ]
    description = document.product_description_containing("弹性云服务器", "ECS")
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
                parser_rule="ecs.product.description",
                target_table="product",
                target_identity="ecs",
                confidence=0.86,
                section_title="product description",
            )
        )
    architecture = infer_ecs_architecture_from_text(document.text)
    if architecture:
        fields.append(
            _candidate(
                field_code="compute.cpu_architecture",
                raw_value=architecture,
                raw_unit=None,
                normalized_value=architecture,
                canonical_unit=None,
                locator="html:document",
                excerpt=_excerpt_around(document.text, architecture),
                parser_rule="ecs.architecture.keyword",
                target_table="product",
                target_identity="ecs",
                confidence=0.82,
                section_title="architecture",
            )
        )
    return fields


def _parse_family_fields(document: HtmlDocument) -> list[tuple[str, list[FieldCandidate]]]:
    families: list[tuple[str, list[FieldCandidate]]] = []
    for index, heading in enumerate(document.soup.find_all(["h1", "h2", "h3", "h4"])):
        text = " ".join(heading.get_text(" ", strip=True).split())
        if not text:
            continue
        family_match = re.search(r"([A-Za-z]?\d+[A-Za-z]?|T\d+|C\d+)", text)
        if not family_match and "型" not in text:
            continue
        family_code = (family_match.group(1) if family_match else text).lower()
        architecture = infer_ecs_architecture_from_text(text)
        fields = [
            _candidate(
                field_code="ecs.instance_family",
                raw_value=text,
                raw_unit=None,
                normalized_value=family_code,
                canonical_unit=None,
                locator=f"html:heading[{index}]",
                excerpt=text,
                parser_rule="ecs.family.heading",
                target_table="product_family",
                target_identity=family_code,
                confidence=0.74 if not family_match else 0.86,
                section_title=text,
            )
        ]
        if architecture:
            fields.append(
                _candidate(
                    field_code="compute.cpu_architecture",
                    raw_value=architecture,
                    raw_unit=None,
                    normalized_value=architecture,
                    canonical_unit=None,
                    locator=f"html:heading[{index}]",
                    excerpt=text,
                    parser_rule="ecs.family.architecture",
                    target_table="product_family",
                    target_identity=family_code,
                    confidence=0.82,
                    section_title=text,
                )
            )
        families.append((family_code, fields))
    return families[:20]


def _parse_sku_rows(document: HtmlDocument) -> list[EcsSkuParsedRow]:
    rows: list[EcsSkuParsedRow] = []
    for table in document.tables():
        header_map = _header_map(table)
        if not {"sku", "vcpu", "memory"} <= set(header_map):
            continue
        for row_index, row in enumerate(table.rows):
            sku = _cell(row, header_map["sku"])
            if not sku:
                continue
            row_text = " | ".join(row)
            rows.append(
                EcsSkuParsedRow(
                    provider_sku_code=sku,
                    sku_family=infer_ecs_family_code(sku),
                    vcpu=_cell(row, header_map.get("vcpu")),
                    memory=_cell(row, header_map.get("memory")),
                    max_bandwidth=_cell(row, header_map.get("bandwidth")),
                    max_pps=_cell(row, header_map.get("pps")),
                    local_disk=_cell(row, header_map.get("local_disk")),
                    virtualization_type=_cell(row, header_map.get("virtualization")),
                    locator=f"{table.locator}:row[{row_index}]",
                    excerpt=row_text,
                )
            )
    return rows[:200]


def _header_map(table: HtmlTable) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(table.headers):
        normalized = header.replace(" ", "").lower()
        if "规格" in header and "名称" in header:
            mapping["sku"] = index
        elif "vcpu" in normalized:
            mapping["vcpu"] = index
        elif "内存" in header:
            mapping["memory"] = index
        elif "带宽" in header:
            mapping["bandwidth"] = index
        elif "pps" in normalized or "收发包" in header:
            mapping["pps"] = index
        elif "本地盘" in header:
            mapping["local_disk"] = index
        elif "虚拟化" in header:
            mapping["virtualization"] = index
    return mapping


def _cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    value = row[index].strip()
    return value or None


def _sku_fields(row: EcsSkuParsedRow) -> list[FieldCandidate]:
    fields = [
        _candidate(
            field_code="sku.provider_sku_code",
            raw_value=row.provider_sku_code,
            raw_unit=None,
            normalized_value=row.provider_sku_code,
            canonical_unit=None,
            locator=row.locator,
            excerpt=row.excerpt,
            parser_rule="ecs.sku.table.provider_sku_code",
            target_table="sku",
            target_identity=row.provider_sku_code,
            confidence=0.92,
            section_title="ECS SKU table",
        )
    ]
    if row.vcpu:
        value = parse_decimal(row.vcpu)
        fields.append(
            _candidate(
                field_code="compute.vcpu_count",
                raw_value=row.vcpu,
                raw_unit="count",
                normalized_value=value,
                canonical_unit="count",
                locator=row.locator,
                excerpt=row.excerpt,
                parser_rule="ecs.sku.table.vcpu",
                target_table="sku",
                target_identity=row.provider_sku_code,
                confidence=0.9 if value is not None else 0.62,
                section_title="ECS SKU table",
            )
        )
    if row.memory:
        value, unit = normalize_memory_to_gib(row.memory)
        fields.append(
            _candidate(
                field_code="compute.memory_gib",
                raw_value=row.memory,
                raw_unit="GiB",
                normalized_value=value,
                canonical_unit=unit,
                locator=row.locator,
                excerpt=row.excerpt,
                parser_rule="ecs.sku.table.memory",
                target_table="sku",
                target_identity=row.provider_sku_code,
                confidence=0.9 if value is not None else 0.62,
                section_title="ECS SKU table",
            )
        )
    if row.max_bandwidth:
        raw_bandwidth = row.max_bandwidth.split("/")[0].strip()
        value, unit = normalize_bandwidth_to_gbps(raw_bandwidth)
        fields.append(
            _candidate(
                field_code="network.max_bandwidth_gbps",
                raw_value=row.max_bandwidth,
                raw_unit="Gbps",
                normalized_value=value,
                canonical_unit=unit,
                locator=row.locator,
                excerpt=row.excerpt,
                parser_rule="ecs.sku.table.max_bandwidth",
                target_table="sku",
                target_identity=row.provider_sku_code,
                confidence=0.84 if value is not None else 0.6,
                section_title="ECS SKU table",
            )
        )
    if row.max_pps:
        value = parse_decimal(row.max_pps)
        fields.append(
            _candidate(
                field_code="network.max_pps",
                raw_value=row.max_pps,
                raw_unit="10k PPS",
                normalized_value=value,
                canonical_unit="10k PPS",
                locator=row.locator,
                excerpt=row.excerpt,
                parser_rule="ecs.sku.table.max_pps",
                target_table="sku",
                target_identity=row.provider_sku_code,
                confidence=0.84 if value is not None else 0.6,
                section_title="ECS SKU table",
            )
        )
    if row.local_disk:
        disk_count, disk_capacity = _parse_local_disk(row.local_disk)
        if disk_count is not None:
            fields.append(
                _candidate(
                    field_code="storage.local_disk_count",
                    raw_value=row.local_disk,
                    raw_unit="count",
                    normalized_value=disk_count,
                    canonical_unit="count",
                    locator=row.locator,
                    excerpt=row.excerpt,
                    parser_rule="ecs.sku.table.local_disk_count",
                    target_table="sku",
                    target_identity=row.provider_sku_code,
                    confidence=0.82,
                    section_title="ECS SKU table",
                )
            )
        if disk_capacity is not None:
            fields.append(
                _candidate(
                    field_code="storage.local_disk_capacity_gib",
                    raw_value=row.local_disk,
                    raw_unit="GiB",
                    normalized_value=disk_capacity,
                    canonical_unit="GiB",
                    locator=row.locator,
                    excerpt=row.excerpt,
                    parser_rule="ecs.sku.table.local_disk_capacity",
                    target_table="sku",
                    target_identity=row.provider_sku_code,
                    confidence=0.82,
                    section_title="ECS SKU table",
                )
            )
    if row.virtualization_type:
        fields.append(
            _candidate(
                field_code="system.virtualization_type",
                raw_value=row.virtualization_type,
                raw_unit=None,
                normalized_value=row.virtualization_type,
                canonical_unit=None,
                locator=row.locator,
                excerpt=row.excerpt,
                parser_rule="ecs.sku.table.virtualization",
                target_table="sku",
                target_identity=row.provider_sku_code,
                confidence=0.86,
                section_title="ECS SKU table",
            )
        )
    return fields


def _parse_local_disk(raw_value: str) -> tuple[Decimal | None, Decimal | None]:
    match = re.search(r"(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)", raw_value)
    if not match:
        return None, None
    return Decimal(match.group(1)), Decimal(match.group(2))


def _parse_sla_fields(
    document: HtmlDocument,
    source_id: str,
) -> list[tuple[str, list[FieldCandidate]]]:
    if not source_id.endswith("_sla"):
        return []
    patterns = (
        (
            "ecs_single_instance",
            "single instance availability",
            r"(单实例[^。；;]*?不低于\s*(\d+(?:\.\d+)?%))",
        ),
        (
            "ecs_multi_az",
            "multi-AZ availability",
            r"(单区域多可用区[^。；;]*?不低于\s*(\d+(?:\.\d+)?%))",
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
                        parser_rule="ecs.sla.availability_commitment",
                        target_table="product_sla",
                        target_identity=scope,
                        confidence=0.86,
                        section_title=section_title,
                    )
                ],
            )
        )
    return results


def _excerpt_around(text: str, keyword: str, radius: int = 120) -> str:
    index = text.find(keyword)
    if index < 0:
        return text[:radius]
    start = max(index - radius // 2, 0)
    end = min(index + radius, len(text))
    return text[start:end]
