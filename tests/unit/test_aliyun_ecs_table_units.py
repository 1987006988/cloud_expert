"""Pure table-parser tests: one source-traced excerpt and labeled synthetic cases."""

from decimal import Decimal
from html import escape

import pytest
from bs4 import BeautifulSoup

from cloud_expert.ingestion.providers.aliyun.ecs.parser import PARSER_VERSION, parse_ecs_document
from cloud_expert.parsing.html_adapter import HtmlDocument
from cloud_expert.parsing.models import FieldCandidate, ParsedRecord

# Minimized HTML retaining the original cell text and help-letter-space markup.
# SourceDocument 47 / SnapshotRecord 47, aliyun_ecs_instance_families,
# html:table[24]:row[1], Evidence 6895-6901. The snapshot's SHA256 is
# c66d579af8c5f0ba68b95e357632f2bb1a0c25b19f65bcf5c38cb609309f9994.
# Original: data/raw/domestic/aliyun/ecs/aliyun_ecs_instance_families/2026/07/
# 20260721T180929Z_c66d579a/raw.bin (verified read-only, not modified).
ARCHIVED_G6_TABLE = """
<table><tr>
<td><p><b>实例规格</b></p></td><td><p><b>vCPU</b></p></td>
<td><p><b>内存（GiB）</b></p></td>
<td><p><b>网络带宽基础/突发（Gbit/s）</b></p></td>
<td><p><b>网络收发包<span class="help-letter-space"></span>PPS</b></p></td>
<td><p><b>连接数</b></p></td><td><p><b>多队列</b></p></td>
<td><p><b>弹性网卡</b></p></td>
<td><p><b>单网卡私有<span class="help-letter-space"></span>IPv4<span class="help-letter-space"></span>地址数</b></p></td>
<td><p><b>单网卡<span class="help-letter-space"></span>IPv6<span class="help-letter-space"></span>地址数</b></p></td>
<td><p><b>云盘基础<span class="help-letter-space"></span>IOPS</b></p></td>
<td><p><b>云盘基础带宽（Gbit/s）</b></p></td>
</tr><tr>
<td><p>ecs.g6.xlarge</p></td><td><p>4</p></td><td><p>16</p></td>
<td><p>1.5/最高<span class="help-letter-space"></span>5</p></td>
<td><p>50<span class="help-letter-space"></span>万</p></td>
<td><p>最高<span class="help-letter-space"></span>25<span class="help-letter-space"></span>万</p></td>
<td><p>4</p></td><td><p>3</p></td><td><p>10</p></td><td><p>1</p></td>
<td><p>2<span class="help-letter-space"></span>万</p></td><td><p>1.5</p></td>
</tr></table>
"""


def _parse(html: str, *, source_id: str = "synthetic_aliyun_ecs_instance_units") -> ParsedRecord:
    soup = BeautifulSoup(html, "html.parser")
    document = HtmlDocument(title="table fixture", text=soup.get_text(" ", strip=True), soup=soup)
    records = parse_ecs_document(document, source_id=source_id, snapshot_id="test-snapshot")
    return next(record for record in records if record.record_type == "aliyun_ecs_sku")


def _synthetic_fields(headers: list[str], cells: list[str]) -> dict[str, FieldCandidate]:
    html = (
        "<table><tr><th>实例规格</th>"
        + "".join(f"<th>{escape(header)}</th>" for header in headers)
        + "</tr><tr><td>ecs.synthetic.large</td>"
        + "".join(f"<td>{escape(cell)}</td>" for cell in cells)
        + "</tr></table>"
    )
    record = _parse(html)
    fields = {field.field_code: field for field in record.fields}
    assert len(fields) == len(record.fields), (
        "A qualifier must not silently overwrite another value"
    )
    return fields


def test_archived_g6_row_keeps_magnitudes_and_baseline_maximum_distinct() -> None:
    record = _parse(ARCHIVED_G6_TABLE, source_id="aliyun_ecs_instance_families")
    fields = {field.field_code: field for field in record.fields}
    expected = {
        "compute.vcpu_count": "4",
        "compute.memory_gib": "16",
        "network.baseline_bandwidth_gbps": "1.5",
        "network.max_bandwidth_gbps": "5",
        "network.max_pps": "500000",
        "network.max_connections": "250000",
        "storage.cloud_disk_baseline_iops": "20000",
        "network.cloud_disk_baseline_bandwidth_gbps": "1.5",
    }
    assert record.target_identity == "ecs.g6.xlarge"
    assert record.parser_version == PARSER_VERSION == "2026.09.c09_aliyun_ecs_table_units_v2"
    for code, value in expected.items():
        assert fields[code].normalized_value == Decimal(value)
        assert fields[code].review_status == "machine_extracted"
    assert "storage.cloud_disk_iops" not in fields
    assert "network.cloud_disk_bandwidth_gbps" not in fields
    assert fields["network.max_connections"].raw_value == "最高 25 万"
    assert fields["storage.cloud_disk_baseline_iops"].raw_value == "2 万"
    for code in ("network.baseline_bandwidth_gbps", "network.max_bandwidth_gbps"):
        assert fields[code].raw_value == "1.5/最高 5"
        assert fields[code].locator == "html:table[0]:row[0]:cell[3]"
        assert "网络带宽基础/突发（Gbit/s）" in fields[code].excerpt
    assert fields["storage.cloud_disk_baseline_iops"].parser_rule.endswith(
        "table_units_v2.baseline"
    )


@pytest.mark.parametrize(
    ("header", "raw", "code", "expected"),
    [
        ("网络收发包 PPS（万）", "50", "network.max_pps", "500000"),
        ("网络收发包 PPS（万）", "50 万", "network.max_pps", "500000"),
        ("网络收发包 PPS（万）", "50 PPS", "network.max_pps", "50"),
        ("网络收发包 PPS", "1.5 MPPS", "network.max_pps", "1500000"),
        ("网络收发包 MPPS", "1.5", "network.max_pps", "1500000"),
        ("网络 pps", "2 kpps", "network.max_pps", "2000"),
        ("连接数", "最大25万", "network.max_connections", "250000"),
        ("连接数（万）", "2.5", "network.max_connections", "25000"),
        ("连接数", "50,000", "network.max_connections", "50000"),
        ("连接数", "50，000", "network.max_connections", "50000"),
        ("连接数", "0.01亿", "network.max_connections", "1000000"),
        ("云盘最大 IOPS", "2 万", "storage.cloud_disk_iops", "20000"),
        ("云盘最大 IOPS（万）", "2 万", "storage.cloud_disk_iops", "20000"),
        ("云盘最大 iops", "20,000 IOPS", "storage.cloud_disk_iops", "20000"),
        ("云盘基础 IOPS", "最高 20 万", "storage.cloud_disk_iops", "200000"),
        ("网络最大带宽（Gbit/s）", "5", "network.max_bandwidth_gbps", "5"),
        ("网络基础带宽（Mbit/s）", "1500", "network.baseline_bandwidth_gbps", "1.5"),
        ("云盘最大带宽（GB/s）", "8", "network.cloud_disk_bandwidth_gbps", "64"),
        ("云盘最大带宽（MB/s）", "125", "network.cloud_disk_bandwidth_gbps", "1"),
        ("云盘最大带宽（Gbit/s）", "125 MB/s", "network.cloud_disk_bandwidth_gbps", "1"),
        ("网络带宽", "up to 500 Mbps", "network.max_bandwidth_gbps", "0.5"),
        ("网络带宽", "maximum 500 Kbit/s", "network.max_bandwidth_gbps", "0.0005"),
    ],
)
def test_synthetic_cell_and_header_units_are_applied_once(
    header: str, raw: str, code: str, expected: str
) -> None:
    field = _synthetic_fields([header], [raw])[code]
    assert field.normalized_value == Decimal(expected)
    assert field.raw_value == raw
    assert header in field.excerpt
    assert field.locator.endswith(":cell[1]")


@pytest.mark.parametrize(
    ("header", "raw", "baseline_code", "maximum_code", "baseline", "maximum"),
    [
        (
            "网络带宽基础/突发（Gbit/s）",
            "1.5/最高 5",
            "network.baseline_bandwidth_gbps",
            "network.max_bandwidth_gbps",
            "1.5",
            "5",
        ),
        (
            "网络带宽基础/突发（Gbit/s）",
            "1.5/5",
            "network.baseline_bandwidth_gbps",
            "network.max_bandwidth_gbps",
            "1.5",
            "5",
        ),
        (
            "网络带宽最大/基准（Gbit/s）",
            "5/1.5",
            "network.baseline_bandwidth_gbps",
            "network.max_bandwidth_gbps",
            "1.5",
            "5",
        ),
        (
            "网络带宽 baseline/burst（Mbit/s）",
            "500 Mbit/s/2 Gbit/s",
            "network.baseline_bandwidth_gbps",
            "network.max_bandwidth_gbps",
            "0.5",
            "2",
        ),
        (
            "云盘 IOPS 基础/突发",
            "2 万/最高 10 万",
            "storage.cloud_disk_baseline_iops",
            "storage.cloud_disk_iops",
            "20000",
            "100000",
        ),
        (
            "云盘 IOPS 基础/突发（万）",
            "2/10",
            "storage.cloud_disk_baseline_iops",
            "storage.cloud_disk_iops",
            "20000",
            "100000",
        ),
        (
            "云盘带宽基础/突发（Gbit/s）",
            "1.5/6",
            "network.cloud_disk_baseline_bandwidth_gbps",
            "network.cloud_disk_bandwidth_gbps",
            "1.5",
            "6",
        ),
    ],
)
def test_synthetic_paired_values_follow_header_order_or_explicit_cell_qualifiers(
    header: str, raw: str, baseline_code: str, maximum_code: str, baseline: str, maximum: str
) -> None:
    fields = _synthetic_fields([header], [raw])
    assert fields[baseline_code].normalized_value == Decimal(baseline)
    assert fields[maximum_code].normalized_value == Decimal(maximum)
    assert fields[baseline_code].raw_value == fields[maximum_code].raw_value == raw
    assert fields[baseline_code].parser_rule != fields[maximum_code].parser_rule


def test_synthetic_missing_burst_is_null_not_baseline_or_zero() -> None:
    fields = _synthetic_fields(["云盘 IOPS 基础/突发（万）"], ["4/无"])
    assert fields["storage.cloud_disk_baseline_iops"].normalized_value == Decimal(40000)
    missing = fields["storage.cloud_disk_iops"]
    assert missing.normalized_value is None
    assert missing.review_status == "pending_review"
    assert missing.raw_value == "4/无"


@pytest.mark.parametrize(
    "raw",
    [
        "无",
        "-",
        "N/A",
        "2-5 万",
        "2 万或 5 万",
        "1/2/3",
        "NaN",
        "-2",
        "1,5",
        "最高 2 万，条件 5",
        "基础最高2万",
    ],
)
def test_synthetic_ambiguous_or_missing_numbers_are_not_first_number_guesses(raw: str) -> None:
    field = _synthetic_fields(["云盘最大 IOPS"], [raw])["storage.cloud_disk_iops"]
    assert field.normalized_value is None
    assert field.review_status == "pending_review"
    assert field.raw_value == raw


def test_synthetic_unlabeled_pair_cannot_invent_baseline_or_maximum() -> None:
    fields = _synthetic_fields(["网络带宽（Gbit/s）"], ["1/最高 5"])
    assert all(
        field.normalized_value is None
        for key, field in fields.items()
        if key != "sku.provider_sku_code"
    )


def test_synthetic_decorated_total_is_not_silently_treated_as_a_scalar() -> None:
    field = _synthetic_fields(["网络基础带宽（Gbit/s）"], ["360（180 * 2）"])[
        "network.baseline_bandwidth_gbps"
    ]
    assert field.normalized_value is None
    assert field.review_status == "pending_review"


def test_synthetic_short_row_does_not_shift_numeric_columns() -> None:
    fields = _synthetic_fields(
        ["vCPU", "内存（GiB）", "网络收发包 PPS", "云盘最大 IOPS"], ["4", "2万", "3万"]
    )
    assert set(fields) == {"sku.provider_sku_code"}


def test_synthetic_similarly_named_columns_do_not_overwrite_primary_numeric_columns() -> None:
    fields = _synthetic_fields(
        [
            "内存（GiB）",
            "持久内存（GiB）",
            "加密内存（GiB）",
            "网络基础带宽（Gbit/s）",
            "RoCE 网络（Gbit/s）",
            "网络收发包 PPS",
            "GPU",
            "GPU 显存",
            "CPU 积分/小时",
        ],
        ["16", "31.5", "8", "3", "200", "20万", "1 * NVIDIA A10", "24 GB", "100"],
    )
    assert fields["compute.memory_gib"].normalized_value == Decimal(16)
    assert fields["network.baseline_bandwidth_gbps"].normalized_value == Decimal(3)
    assert fields["network.max_pps"].normalized_value == Decimal(200000)
    assert fields["gpu.count"].normalized_value == Decimal(1)
    assert "compute.processor_model" not in fields
