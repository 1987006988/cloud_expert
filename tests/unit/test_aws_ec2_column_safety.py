"""Synthetic table regressions only; these fixtures make no cloud product claims."""

from decimal import Decimal
from html import escape
from itertools import permutations

import pytest
from bs4 import BeautifulSoup

from cloud_expert.ingestion.providers.aws.common import PARSER_VERSION
from cloud_expert.ingestion.providers.aws.ec2.parser import (
    _architecture_from_processor,
    _ec2_memory_cell,
    _ec2_processor_cell,
    _looks_like_memory_value,
    _processor_vendor,
    parse_ec2_document,
)
from cloud_expert.parsing.html_adapter import HtmlDocument
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord

SOURCE_ID = "synthetic_aws_ec2_column_safety"
SNAPSHOT_ID = "synthetic-column-safety-snapshot"
SKU = "synthetic.large"
MEMORY = "compute.memory_gib"
MODEL = "compute.processor_model"
VENDOR = "compute.processor_vendor"
ARCHITECTURE = "compute.cpu_architecture"


def _records(headers: list[str], row: list[str]) -> list[ParsedRecord]:
    header_html = "".join(f"<th>{escape(value)}</th>" for value in headers)
    row_html = "".join(f"<td>{escape(value)}</td>" for value in row)
    soup = BeautifulSoup(
        f"<html><h1>Synthetic table</h1><table><tr>{header_html}</tr>"
        f"<tr>{row_html}</tr></table></html>",
        "html.parser",
    )
    document = HtmlDocument(
        title="Synthetic table",
        text=" ".join(soup.get_text(" ", strip=True).split()),
        soup=soup,
    )
    return parse_ec2_document(document, source_id=SOURCE_ID, snapshot_id=SNAPSHOT_ID)


def _fields(headers: list[str], row: list[str]) -> dict[str, FieldCandidate]:
    records = _records(headers, row)
    sku = next(record for record in records if record.record_type == "ec2_sku")
    return {field.field_code: field for field in sku.fields}


def test_xeon_digits_in_memory_column_are_not_memory() -> None:
    fields = _fields(
        ["Instance type", "Memory (GiB)", "Processor", "vCPUs"],
        [SKU, "Intel Xeon Platinum 8124M", "2", "4"],
    )
    assert MEMORY not in fields
    assert MODEL not in fields
    assert VENDOR not in fields
    assert ARCHITECTURE not in fields
    assert fields["compute.vcpu_count"].normalized_value == Decimal("4")


def test_invalid_header_bound_cells_never_fall_back_to_other_columns() -> None:
    fields = _fields(
        ["Instance type", "Network cards", "Notes", "Memory (GiB)", "Processor"],
        [SKU, "4", "Intel Xeon 8124M", "\u2717 No", "Unknown"],
    )
    assert {MEMORY, MODEL, VENDOR, ARCHITECTURE}.isdisjoint(fields)


@pytest.mark.parametrize(
    "headers,row",
    [
        (["Instance type", "Network cards", "Notes"], [SKU, "4", "Intel Xeon 8124M"]),
        (["Instance type", "vCPUs", "Processor count"], [SKU, "4", "2"]),
        (["Instance type", "EBS encryption", "NitroTPM"], [SKU, "Yes", "\u2717 No"]),
    ],
)
def test_missing_headers_do_not_infer_memory_or_processor(
    headers: list[str], row: list[str]
) -> None:
    assert {MEMORY, MODEL, VENDOR, ARCHITECTURE}.isdisjoint(_fields(headers, row))


@pytest.mark.parametrize(
    "ordered_columns",
    list(permutations([("Memory (GiB)", "8"), ("Processor", "Intel Xeon 8124M"), ("vCPUs", "2")])),
)
def test_reordered_headers_bind_the_same_fields(
    ordered_columns: tuple[tuple[str, str], ...],
) -> None:
    headers = [header for header, _ in ordered_columns]
    row = [value for _, value in ordered_columns]
    # The instance identifier need not be the first column either.
    headers.insert(1, "Instance type")
    row.insert(1, SKU)
    fields = _fields(headers, row)
    assert fields[MEMORY].normalized_value == Decimal("8")
    assert fields[MODEL].raw_value == "Intel Xeon 8124M"
    assert fields[VENDOR].normalized_value == "Intel"
    assert fields[ARCHITECTURE].normalized_value == "x86_64"
    assert fields["compute.vcpu_count"].normalized_value == Decimal("2")


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "inf",
        "-8",
        "-0",
        "0",
        "0.00 GiB",
        "+8",
        "1e3",
        "8-16",
        "8 / 16",
        "Up to 8",
        "8 GiB extra",
        "2 processors",
        "Intel Xeon8124M",
        "Intel Xeon Platinum 8124M",
        "4 Gbps",
        "4 Gb",
        "4 gib",
        "4 GB/s",
        "4%",
        "Yes",
        "No",
        "True",
        "False",
        "Supported",
        "\u2713 Yes",
        "\u2717 No",
        "1,02",
        "1,000,00",
        "1 024",
        "8.0.0",
        "1_024",
    ],
)
def test_memory_requires_a_complete_positive_numeric_token(value: str) -> None:
    assert not _looks_like_memory_value(value)
    fields = _fields(["Instance type", "Memory (GiB)"], [SKU, value])
    assert MEMORY not in fields


@pytest.mark.parametrize(
    "header,value,unit,expected",
    [
        ("Memory (GiB)", "8", "GiB", "8"),
        ("Memory (GiB)", "8.00 GiB", "GiB", "8"),
        ("Memory", "8 GiB", "GiB", "8"),
        ("Memory GiB", ".5", "GiB", "0.5"),
        ("Memory size (GiB)", "1,024", "GiB", "1024"),
        ("Memory capacity (GiB)", "1,024.5", "GiB", "1024.5"),
        ("Memory (MiB)", "4096", "MiB", "4"),
        ("Memory", "4096 MiB", "MiB", "4"),
        ("Memory (TiB)", "1", "TiB", "1024"),
        ("Memory (GB)", "8", "GB", "7.450580596923828125"),
        ("Memory", "8 GB", "GB", "7.450580596923828125"),
        ("Memory (MB)", "1024", "MB", "0.95367431640625"),
        ("Memory (TB)", "1", "TB", "931.322574615478515625"),
    ],
)
def test_explicit_memory_units_are_preserved_and_converted(
    header: str, value: str, unit: str, expected: str
) -> None:
    field = _fields(["Instance type", header], [SKU, value])[MEMORY]
    assert field.raw_value == value
    assert field.raw_unit == unit
    assert field.normalized_value == Decimal(expected)
    assert field.canonical_unit == "GiB"


@pytest.mark.parametrize(
    "header,value",
    [
        ("Memory", "8"),
        ("Memory (GiB)", "8 GB"),
        ("Memory (GB)", "8 GiB"),
        ("Memory (GiB)", "8192 MiB"),
        ("Memory (Gb)", "8"),
        ("Memory (unknown)", "8 GiB"),
        ("GPU memory (GiB)", "8"),
        ("Accelerator memory", "8 GiB"),
        ("Memory per vCPU (GiB)", "8"),
        ("Memory bandwidth", "8 GiB"),
    ],
)
def test_unknown_conflicting_or_unrelated_memory_headers_fail_closed(
    header: str, value: str
) -> None:
    assert MEMORY not in _fields(["Instance type", header], [SKU, value])


def test_duplicate_memory_and_processor_headers_are_ambiguous() -> None:
    fields = _fields(
        ["Instance type", "Memory (GiB)", "Memory (GB)", "Processor", "Physical processor"],
        [SKU, "8", "16", "Intel Xeon", "AWS Graviton3"],
    )
    assert {MEMORY, MODEL, VENDOR, ARCHITECTURE}.isdisjoint(fields)


@pytest.mark.parametrize(
    "row",
    [[SKU, "8"], [SKU, "8", "Intel Xeon", "2", "extra"]],
)
def test_malformed_rows_are_not_positionally_realigned(row: list[str]) -> None:
    records = _records(["Instance type", "Memory (GiB)", "Processor", "vCPUs"], row)
    assert not any(record.record_type == "ec2_sku" for record in records)


@pytest.mark.parametrize("index", [None, -1, 10])
def test_unbound_or_out_of_range_cells_do_not_fall_back(index: int | None) -> None:
    row = [SKU, "8", "Intel Xeon"]
    memory_map = {} if index is None else {"memory": index}
    processor_map = {} if index is None else {"processor": index}
    assert _ec2_memory_cell(row, memory_map) is None
    assert _ec2_processor_cell(row, processor_map) is None
    assert row == [SKU, "8", "Intel Xeon"]


@pytest.mark.parametrize(
    "processor,vendor,architecture",
    [
        ("Intel Xeon Platinum 8124M", "Intel", "x86_64"),
        ("Intel Xeon8124M", "Intel", "x86_64"),
        ("AMD EPYC synthetic", "AMD", "x86_64"),
        ("AWS Graviton3 Processor", "AWS Graviton", "arm64"),
        ("AWS Graviton3E (ARM64)", "AWS Graviton", "arm64"),
        ("Intel Xeon (x86_64)", "Intel", "x86_64"),
        ("ARM Neoverse", None, "arm64"),
        ("aarch64", None, "arm64"),
        ("amd64", None, "x86_64"),
    ],
)
def test_consistent_processor_tokens_determine_architecture(
    processor: str, vendor: str | None, architecture: str
) -> None:
    fields = _fields(["Instance type", "Processor"], [SKU, processor])
    assert fields[MODEL].raw_value == processor
    assert fields[ARCHITECTURE].normalized_value == architecture
    assert _processor_vendor(processor) == vendor
    if vendor:
        assert fields[VENDOR].normalized_value == vendor
    else:
        assert VENDOR not in fields


@pytest.mark.parametrize(
    "processor",
    [
        "Intel Xeon / AWS Graviton3",
        "AMD EPYC + Graviton4",
        "Intel (ARM64)",
        "Graviton3 x86_64",
        "Intel AMD",
        "AMD Xeon",
        "Intel Neoverse",
        "Intel armv7",
        "ARM64 x86_64",
        "ARM32",
        "ARMv7",
        "i386",
        "x86_32",
        "32-bit Intel Xeon",
    ],
)
def test_conflicting_or_unsupported_processor_tokens_do_not_infer_architecture(
    processor: str,
) -> None:
    fields = _fields(["Instance type", "Processor"], [SKU, processor])
    assert fields[MODEL].raw_value == processor
    assert VENDOR not in fields
    assert ARCHITECTURE not in fields
    assert _processor_vendor(processor) is None
    assert _architecture_from_processor(processor) is None


@pytest.mark.parametrize(
    "processor",
    [
        "farm",
        "charm",
        "warm",
        "intellectual",
        "preAMDpost",
        "Gravitonish",
        "2",
        "8 GiB",
        "True",
        "False",
        "\u2717 No",
        "processor count 2",
        "unknown",
    ],
)
def test_unrelated_words_and_invalid_processor_cells_do_not_infer_architecture(
    processor: str,
) -> None:
    fields = _fields(["Instance type", "Processor"], [SKU, processor])
    assert {MODEL, VENDOR, ARCHITECTURE}.isdisjoint(fields)
    assert _architecture_from_processor(processor) is None


@pytest.mark.parametrize("header", ["Processor count", "Processor support", "Notes", "Network"])
def test_processor_text_under_wrong_header_does_not_generate_architecture(header: str) -> None:
    fields = _fields(["Instance type", "Memory (GiB)", header], [SKU, "8", "Intel Xeon"])
    assert {MODEL, VENDOR, ARCHITECTURE}.isdisjoint(fields)
    assert fields[MEMORY].normalized_value == Decimal("8")


def test_parser_version_and_source_evidence_remain_attached() -> None:
    headers = ["Instance type", "Memory (GiB)", "Processor", "ENA Express"]
    row = [SKU, "8.00", "Intel Xeon 8124M", "\u2717 No"]
    records = _records(headers, row)
    assert PARSER_VERSION == "2026.09.c09_aws_ec2_column_safety_v2"
    assert all(record.parser_version == PARSER_VERSION for record in records)
    assert all(
        record.source_id == SOURCE_ID and record.snapshot_id == SNAPSHOT_ID for record in records
    )
    sku = next(record for record in records if record.record_type == "ec2_sku")
    assert sku.target_identity == SKU
    assert all(field.excerpt == " | ".join(row) for field in sku.fields)
    assert all(field.locator == "html:table[0]:row[0]" for field in sku.fields)
    fields = {field.field_code: field for field in sku.fields}
    assert fields[MEMORY].raw_value == "8.00"
    assert fields[MODEL].raw_value == "Intel Xeon 8124M"
    assert fields["network.ena_express_supported"].raw_value == "\u2717 No"
    assert headers == ["Instance type", "Memory (GiB)", "Processor", "ENA Express"]
    assert row == [SKU, "8.00", "Intel Xeon 8124M", "\u2717 No"]
