from decimal import Decimal

from cloud_expert.database.enums import DataType
from cloud_expert.normalization.booleans import normalize_boolean
from cloud_expert.normalization.percentages import normalize_percentage
from cloud_expert.normalization.unit_standardization import format_decimal, standardize_value
from cloud_expert.normalization.units import (
    normalize_bandwidth_to_gbps,
    normalize_days,
    normalize_memory_to_gib,
    parse_decimal,
)


def test_boolean_normalization_supports_ascii_and_chinese_tokens() -> None:
    assert normalize_boolean(" supported ") is True
    assert normalize_boolean("支持") is True
    assert normalize_boolean("not supported") is False
    assert normalize_boolean("不支持") is False
    assert normalize_boolean("needs judgement") is None


def test_unit_helpers_parse_memory_bandwidth_days_and_percentages() -> None:
    assert parse_decimal("1,024.5 GiB") == Decimal("1024.5")
    assert parse_decimal("not numeric") is None
    assert normalize_memory_to_gib("2 TiB") == (Decimal("2048"), "GiB")
    assert normalize_memory_to_gib("512 MiB") == (Decimal("0.5"), "GiB")
    assert normalize_memory_to_gib("unknown") == (None, None)
    assert normalize_bandwidth_to_gbps("500 Mbps") == (Decimal("0.5"), "Gbps")
    assert normalize_days("30 days") == (30, "day")
    assert normalize_percentage("99.99%") == Decimal("99.99")
    assert normalize_percentage("") is None


def test_standardize_value_covers_review_and_conversion_paths() -> None:
    supported = standardize_value(
        data_type=DataType.BOOLEAN.value,
        raw_value="supported",
        numeric_value=None,
        text_value=None,
        boolean_value=None,
        raw_unit=None,
        source_canonical_unit=None,
        target_unit=None,
    )
    assert supported.boolean_value is True

    boolean = standardize_value(
        data_type=DataType.BOOLEAN.value,
        raw_value="maybe",
        numeric_value=None,
        text_value=None,
        boolean_value=None,
        raw_unit=None,
        source_canonical_unit=None,
        target_unit=None,
    )
    assert boolean.requires_review is True
    assert boolean.conversion_notes == "Boolean value requires manual review."

    text = standardize_value(
        data_type=DataType.TEXT.value,
        raw_value="official text",
        numeric_value=None,
        text_value=None,
        boolean_value=None,
        raw_unit=None,
        source_canonical_unit=None,
        target_unit=None,
    )
    assert text.text_value == "official text"

    gib = standardize_value(
        data_type=DataType.NUMERIC.value,
        raw_value="1",
        numeric_value=Decimal("1"),
        text_value=None,
        boolean_value=None,
        raw_unit="TiB",
        source_canonical_unit=None,
        target_unit="GiB",
    )
    assert gib.numeric_value == Decimal("1024")
    assert gib.requires_review is False

    ambiguous = standardize_value(
        data_type=DataType.NUMERIC.value,
        raw_value="1",
        numeric_value=Decimal("1"),
        text_value=None,
        boolean_value=None,
        raw_unit="GB",
        source_canonical_unit=None,
        target_unit="GiB",
    )
    assert ambiguous.requires_review is True

    unknown = standardize_value(
        data_type=DataType.NUMERIC.value,
        raw_value="not parseable",
        numeric_value=None,
        text_value=None,
        boolean_value=None,
        raw_unit=None,
        source_canonical_unit=None,
        target_unit="synthetic-unit",
    )
    assert unknown.requires_review is True
    assert unknown.text_value == "not parseable"
    assert format_decimal(Decimal("1.2300")) == "1.23"


def test_standardize_value_covers_numeric_unit_matrix() -> None:
    cases = [
        ("10", "count", "count", Decimal("10"), False),
        ("1", "MiB", "KiB", Decimal("1024"), False),
        ("1", "GiB", "KiB", Decimal("1048576"), False),
        ("1", "parsec", "KiB", Decimal("1"), True),
        ("1000", "Kbps", "Gbps", Decimal("0.001"), False),
        ("100", "MB/s", "Gbps", Decimal("0.8"), True),
        ("1", "mystery", "Gbps", Decimal("1"), True),
        ("2", "Kpps", "PPS", Decimal("2000"), False),
        ("3", "Mpps", "PPS", Decimal("3000000"), False),
        ("4", "unknown", "PPS", Decimal("4"), True),
        ("5", None, None, Decimal("5"), False),
    ]
    for raw_value, raw_unit, target_unit, expected, requires_review in cases:
        result = standardize_value(
            data_type=DataType.NUMERIC.value,
            raw_value=raw_value,
            numeric_value=None,
            text_value=None,
            boolean_value=None,
            raw_unit=raw_unit,
            source_canonical_unit=None,
            target_unit=target_unit,
        )
        assert result.numeric_value == expected
        assert result.requires_review is requires_review
