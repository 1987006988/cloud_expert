import re
from decimal import Decimal

from cloud_expert.database.enums import AvailabilityStatus, ReviewStatus
from cloud_expert.ingestion.providers.aws.common import (
    AWS_COMMERCIAL_PARTITION,
    PARSER_VERSION,
)
from cloud_expert.normalization.ecs import infer_ecs_family_code
from cloud_expert.normalization.percentages import normalize_percentage
from cloud_expert.normalization.units import (
    normalize_bandwidth_to_gbps,
    normalize_memory_to_gib,
    parse_decimal,
)
from cloud_expert.parsing.html_adapter import HtmlDocument, HtmlTable
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord

INSTANCE_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*\.[a-z0-9.:-]+$", re.IGNORECASE)
REGION_CODE_PATTERN = re.compile(r"^(?!cn-)(?!us-gov-)[a-z]{2}-[a-z-]+-\d+$")


def parse_ec2_document(
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
                target_identity="ec2",
                fields=product_fields,
                parser_version=PARSER_VERSION,
            )
        )

    records.extend(_instance_records(document, source_id, snapshot_id))
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
    official_name = "Amazon Elastic Compute Cloud (Amazon EC2)"
    fields = [
        _candidate(
            field_code="product.official_name",
            raw_value=official_name,
            raw_unit=None,
            normalized_value=official_name,
            canonical_unit=None,
            locator="html:h1",
            excerpt=heading or official_name,
            parser_rule="aws.ec2.product.official_name",
            target_table="product",
            target_identity="ec2",
            confidence=0.9,
            section_title="product heading",
        )
    ]
    paragraphs = document.paragraphs_containing("Amazon EC2", "Elastic Compute Cloud")
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
                parser_rule="aws.ec2.product.description",
                target_table="product",
                target_identity="ec2",
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
    records: list[ParsedRecord] = []
    seen_families: set[str] = set()
    for table in document.tables():
        header_map = _header_map(table)
        instance_index = header_map.get("instance")
        if instance_index is None:
            continue
        for row_index, row in enumerate(table.rows):
            instance_type = _cell(row, instance_index)
            if not instance_type or not INSTANCE_TYPE_PATTERN.match(instance_type):
                continue
            excerpt = " | ".join(row)
            locator = f"{table.locator}:row[{row_index}]"
            family_code = infer_ecs_family_code(instance_type)
            if family_code not in seen_families:
                seen_families.add(family_code)
                records.append(
                    ParsedRecord(
                        record_type="ec2_instance_family",
                        source_id=source_id,
                        snapshot_id=snapshot_id,
                        target_identity=family_code,
                        fields=_family_fields(family_code, locator, excerpt),
                        parser_version=PARSER_VERSION,
                    )
                )
            sku_fields = _sku_fields(row, header_map, instance_type, locator, excerpt)
            if sku_fields:
                records.append(
                    ParsedRecord(
                        record_type="ec2_sku",
                        source_id=source_id,
                        snapshot_id=snapshot_id,
                        target_identity=instance_type,
                        fields=sku_fields,
                        parser_version=PARSER_VERSION,
                    )
                )
    return records[:500]


def _family_fields(family_code: str, locator: str, excerpt: str) -> list[FieldCandidate]:
    return [
        _candidate(
            field_code="ec2.instance_family",
            raw_value=family_code,
            raw_unit=None,
            normalized_value=family_code,
            canonical_unit=None,
            locator=locator,
            excerpt=excerpt,
            parser_rule="aws.ec2.family.from_instance_type",
            target_table="product_family",
            target_identity=family_code,
            confidence=0.86,
            section_title="EC2 instance family",
        )
    ]


def _sku_fields(
    row: list[str],
    header_map: dict[str, int],
    instance_type: str,
    locator: str,
    excerpt: str,
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
            parser_rule="aws.ec2.sku.instance_type",
            target_table="sku",
            target_identity=instance_type,
            confidence=0.93,
            section_title="EC2 instance table",
        )
    ]
    _add_numeric_field(
        fields,
        row,
        header_map,
        key="vcpu",
        field_code="compute.vcpu_count",
        unit="count",
        canonical_unit="count",
        parser_rule="aws.ec2.sku.vcpu",
        target_identity=instance_type,
        locator=locator,
        excerpt=excerpt,
        normalizer=parse_decimal,
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
                parser_rule="aws.ec2.sku.memory",
                target_table="sku",
                target_identity=instance_type,
                confidence=0.9 if value is not None else 0.62,
                section_title="EC2 instance table",
            )
        )
    processor = _cell(row, header_map.get("processor"))
    if processor:
        fields.append(
            _candidate(
                field_code="compute.processor_model",
                raw_value=processor,
                raw_unit=None,
                normalized_value=processor,
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.processor_model",
                target_table="sku",
                target_identity=instance_type,
                confidence=0.84,
                section_title="EC2 instance table",
            )
        )
        vendor = _processor_vendor(processor)
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
                    parser_rule="aws.ec2.sku.processor_vendor",
                    target_table="sku",
                    target_identity=instance_type,
                    confidence=0.82,
                    section_title="EC2 instance table",
                )
            )
        architecture = _architecture_from_processor(processor)
        if architecture:
            fields.append(
                _candidate(
                    field_code="compute.cpu_architecture",
                    raw_value=processor,
                    raw_unit=None,
                    normalized_value=architecture,
                    canonical_unit=None,
                    locator=locator,
                    excerpt=excerpt,
                    parser_rule="aws.ec2.sku.cpu_architecture",
                    target_table="sku",
                    target_identity=instance_type,
                    confidence=0.76,
                    section_title="EC2 instance table",
                )
            )
    network = _cell(row, header_map.get("network"))
    if network:
        baseline, maximum = _parse_network_bandwidth(network)
        if baseline is not None:
            fields.append(_bandwidth_candidate("network.baseline_bandwidth_gbps", network, baseline, locator, excerpt, instance_type, "aws.ec2.sku.network_baseline"))
        if maximum is not None:
            fields.append(_bandwidth_candidate("network.max_bandwidth_gbps", network, maximum, locator, excerpt, instance_type, "aws.ec2.sku.network_max"))
    ebs = _cell(row, header_map.get("ebs"))
    if ebs:
        value, unit = _parse_best_effort_bandwidth(ebs)
        fields.append(
            _candidate(
                field_code="network.ebs_bandwidth_gbps",
                raw_value=ebs,
                raw_unit="Gbps",
                normalized_value=value,
                canonical_unit=unit,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.ebs_bandwidth",
                target_table="sku",
                target_identity=instance_type,
                confidence=0.8 if value is not None else 0.58,
                section_title="EC2 EBS table",
            )
        )
    ena_express = _cell(row, header_map.get("ena_express"))
    if ena_express:
        fields.append(
            _candidate(
                field_code="network.ena_express_supported",
                raw_value=ena_express,
                raw_unit=None,
                normalized_value=_truthy_support(ena_express),
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.ena_express",
                target_table="sku",
                target_identity=instance_type,
                confidence=0.82,
                section_title="EC2 network table",
            )
        )
    storage = _cell(row, header_map.get("storage"))
    if storage:
        fields.extend(_storage_fields(storage, locator, excerpt, instance_type))
    accelerator = _cell(row, header_map.get("accelerator"))
    if accelerator:
        fields.extend(_accelerator_fields(accelerator, locator, excerpt, instance_type))
    return fields


def _bandwidth_candidate(
    field_code: str,
    raw_value: str,
    normalized_value: Decimal,
    locator: str,
    excerpt: str,
    target_identity: str,
    parser_rule: str,
) -> FieldCandidate:
    return _candidate(
        field_code=field_code,
        raw_value=raw_value,
        raw_unit="Gbps",
        normalized_value=normalized_value,
        canonical_unit="Gbps",
        locator=locator,
        excerpt=excerpt,
        parser_rule=parser_rule,
        target_table="sku",
        target_identity=target_identity,
        confidence=0.8,
        section_title="EC2 network table",
    )


def _add_numeric_field(
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
    normalizer: object,
) -> None:
    raw_value = _cell(row, header_map.get(key))
    if not raw_value:
        return
    value = normalizer(raw_value)  # type: ignore[operator]
    fields.append(
        _candidate(
            field_code=field_code,
            raw_value=raw_value,
            raw_unit=unit,
            normalized_value=value,
            canonical_unit=canonical_unit,
            locator=locator,
            excerpt=excerpt,
            parser_rule=parser_rule,
            target_table="sku",
            target_identity=target_identity,
            confidence=0.9 if value is not None else 0.62,
            section_title="EC2 instance table",
        )
    )


def _storage_fields(
    raw_value: str,
    locator: str,
    excerpt: str,
    target_identity: str,
) -> list[FieldCandidate]:
    fields: list[FieldCandidate] = []
    if raw_value.lower() in {"no", "none", "ebs only", "ebs-only"}:
        return fields
    match = re.search(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*([a-z]+)?", raw_value, re.IGNORECASE)
    if match:
        fields.append(
            _candidate(
                field_code="storage.local_disk_count",
                raw_value=raw_value,
                raw_unit="count",
                normalized_value=Decimal(match.group(1)),
                canonical_unit="count",
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.local_disk_count",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.82,
                section_title="EC2 storage table",
            )
        )
        capacity, unit = normalize_memory_to_gib(f"{match.group(2)} {match.group(3) or 'GB'}")
        fields.append(
            _candidate(
                field_code="storage.local_disk_capacity_gib",
                raw_value=raw_value,
                raw_unit=match.group(3) or "GB",
                normalized_value=capacity,
                canonical_unit=unit,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.local_disk_capacity",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.82 if capacity is not None else 0.6,
                section_title="EC2 storage table",
            )
        )
    storage_type_match = re.search(r"(NVMe SSD|SSD|HDD)", raw_value, re.IGNORECASE)
    if storage_type_match:
        fields.append(
            _candidate(
                field_code="storage.local_disk_type",
                raw_value=storage_type_match.group(1),
                raw_unit=None,
                normalized_value=storage_type_match.group(1),
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.local_disk_type",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.82,
                section_title="EC2 storage table",
            )
        )
    return fields


def _accelerator_fields(
    raw_value: str,
    locator: str,
    excerpt: str,
    target_identity: str,
) -> list[FieldCandidate]:
    if raw_value.lower() in {"no", "none", "n/a"}:
        return []
    count = parse_decimal(raw_value)
    model_match = re.search(r"(NVIDIA|AMD|Inferentia|Trainium)[^,;|]*", raw_value, re.IGNORECASE)
    fields: list[FieldCandidate] = []
    if count is not None:
        fields.append(
            _candidate(
                field_code="gpu.count",
                raw_value=raw_value,
                raw_unit="count",
                normalized_value=count,
                canonical_unit="count",
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.accelerator_count",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.72,
                section_title="EC2 accelerator table",
            )
        )
    if model_match:
        fields.append(
            _candidate(
                field_code="gpu.model",
                raw_value=model_match.group(0),
                raw_unit=None,
                normalized_value=model_match.group(0),
                canonical_unit=None,
                locator=locator,
                excerpt=excerpt,
                parser_rule="aws.ec2.sku.accelerator_model",
                target_table="sku",
                target_identity=target_identity,
                confidence=0.72,
                section_title="EC2 accelerator table",
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
                            parser_rule="aws.ec2.region.partition",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.9,
                            section_title="EC2 endpoints table",
                        ),
                        _candidate(
                            field_code="region.code",
                            raw_value=region_code,
                            raw_unit=None,
                            normalized_value=region_code,
                            canonical_unit=None,
                            locator=locator,
                            excerpt=excerpt,
                            parser_rule="aws.ec2.region.code",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.92,
                            section_title="EC2 endpoints table",
                        ),
                        _candidate(
                            field_code="region.name",
                            raw_value=name,
                            raw_unit=None,
                            normalized_value=name,
                            canonical_unit=None,
                            locator=locator,
                            excerpt=excerpt,
                            parser_rule="aws.ec2.region.name",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.9,
                            section_title="EC2 endpoints table",
                        ),
                        _candidate(
                            field_code="availability.status",
                            raw_value=AvailabilityStatus.AVAILABLE.value,
                            raw_unit=None,
                            normalized_value=AvailabilityStatus.AVAILABLE.value,
                            canonical_unit=None,
                            locator=locator,
                            excerpt=excerpt,
                            parser_rule="aws.ec2.region.available",
                            target_table="availability",
                            target_identity=region_code,
                            confidence=0.84,
                            section_title="EC2 endpoints table",
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
    scopes = {
        "ec2_region_level": ("region-level", "Region-Level SLA"),
        "ec2_instance_level": ("instance-level", "Instance-Level SLA"),
    }
    records: list[ParsedRecord] = []
    lower_text = document.text.lower()
    for scope, (needle, label) in scopes.items():
        index = lower_text.find(needle)
        if index < 0:
            continue
        excerpt = document.text[index : index + 700]
        percent = _percentage_from_text(excerpt)
        if percent is None:
            continue
        records.append(
            ParsedRecord(
                record_type="product_sla",
                source_id=source_id,
                snapshot_id=snapshot_id,
                target_identity=scope,
                fields=[
                    _candidate(
                        field_code="sla.availability_percentage",
                        raw_value=percent,
                        raw_unit="percent",
                        normalized_value=normalize_percentage(percent),
                        canonical_unit="percent",
                        locator=f"html:text:sla:{scope}",
                        excerpt=excerpt,
                        parser_rule="aws.ec2.sla.availability_commitment",
                        target_table="product_sla",
                        target_identity=scope,
                        confidence=0.82,
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
        if "instancetype" in normalized:
            mapping["instance"] = index
        elif "vcpu" in normalized:
            mapping["vcpu"] = index
        elif "memory" in normalized:
            mapping["memory"] = index
        elif "processor" in normalized:
            mapping["processor"] = index
        elif "baseline" in normalized and "burst" in normalized and "bandwidth" in normalized or "networkperformance" in normalized or (
            "bandwidth" in normalized and "ebs" not in normalized
        ):
            mapping["network"] = index
        elif "ebs" in normalized and "bandwidth" in normalized:
            mapping["ebs"] = index
        elif "enaexpress" in normalized:
            mapping["ena_express"] = index
        elif "instancestore" in normalized or "instancestorage" in normalized:
            mapping["storage"] = index
        elif "accelerator" in normalized or "gpu" in normalized:
            mapping["accelerator"] = index
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


def _processor_vendor(value: str) -> str | None:
    lowered = value.lower()
    if "graviton" in lowered:
        return "AWS Graviton"
    if "intel" in lowered or "xeon" in lowered:
        return "Intel"
    if "amd" in lowered or "epyc" in lowered:
        return "AMD"
    return None


def _architecture_from_processor(value: str) -> str | None:
    lowered = value.lower()
    if "graviton" in lowered or "arm" in lowered:
        return "arm64"
    if any(token in lowered for token in ("intel", "xeon", "amd", "epyc")):
        return "x86_64"
    return None


def _parse_network_bandwidth(raw_value: str) -> tuple[Decimal | None, Decimal | None]:
    values = [Decimal(match) for match in re.findall(r"\d+(?:\.\d+)?", raw_value.replace(",", ""))]
    if not values:
        return None, None
    if "/" in raw_value and len(values) >= 2:
        return values[0], values[1]
    if "up to" in raw_value.lower():
        return None, values[-1]
    return None, values[-1]


def _parse_best_effort_bandwidth(raw_value: str) -> tuple[Decimal | None, str | None]:
    value, unit = normalize_bandwidth_to_gbps(raw_value)
    if value is None:
        return None, None
    if "mbps" in raw_value.lower():
        return value, unit
    return value, "Gbps"


def _truthy_support(raw_value: str) -> bool | None:
    lowered = raw_value.lower()
    if lowered in {"yes", "supported", "true"}:
        return True
    if lowered in {"no", "not supported", "false"}:
        return False
    return None


def _percentage_from_text(text: str) -> str | None:
    match = re.search(r"\d+(?:\.\d+)?\s*%", text)
    return match.group(0) if match else None
