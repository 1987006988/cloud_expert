from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from cloud_expert.database.enums import DataType
from cloud_expert.normalization.units import parse_decimal


@dataclass(frozen=True)
class StandardizedValue:
    numeric_value: Decimal | None
    text_value: str | None
    boolean_value: bool | None
    canonical_value: str | None
    canonical_unit: str | None
    conversion_notes: str | None
    requires_review: bool = False


def standardize_value(
    *,
    data_type: str,
    raw_value: str,
    numeric_value: Decimal | int | float | None,
    text_value: str | None,
    boolean_value: bool | None,
    raw_unit: str | None,
    source_canonical_unit: str | None,
    target_unit: str | None,
) -> StandardizedValue:
    if data_type == DataType.BOOLEAN.value:
        bool_result = (
            boolean_value if boolean_value is not None else _parse_boolean(text_value or raw_value)
        )
        return StandardizedValue(
            numeric_value=None,
            text_value=None,
            boolean_value=bool_result,
            canonical_value=None if bool_result is None else str(bool_result).lower(),
            canonical_unit=None,
            conversion_notes=None
            if bool_result is not None
            else "Boolean value requires manual review.",
            requires_review=bool_result is None,
        )
    if data_type in {DataType.TEXT.value, DataType.ENUM.value}:
        text_result = text_value if text_value is not None else raw_value
        return StandardizedValue(
            numeric_value=None,
            text_value=text_result,
            boolean_value=None,
            canonical_value=text_result,
            canonical_unit=target_unit,
            conversion_notes=None,
        )

    decimal_result = _decimal_or_none(numeric_value) or parse_decimal(raw_value)
    if decimal_result is None:
        return StandardizedValue(
            numeric_value=None,
            text_value=raw_value,
            boolean_value=None,
            canonical_value=raw_value,
            canonical_unit=target_unit,
            conversion_notes="Numeric value could not be parsed; retained as text for review.",
            requires_review=True,
        )

    source_unit = _normalize_unit(raw_unit or source_canonical_unit or target_unit)
    normalized, notes, requires_review = _convert_numeric(decimal_result, source_unit, target_unit)
    return StandardizedValue(
        numeric_value=normalized,
        text_value=None,
        boolean_value=None,
        canonical_value=format_decimal(normalized),
        canonical_unit=target_unit or source_canonical_unit or raw_unit,
        conversion_notes=notes,
        requires_review=requires_review,
    )


def format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f").rstrip("0").rstrip(".")


def _decimal_or_none(value: Decimal | int | float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return unit.strip().lower().replace(" ", "")


def _convert_numeric(
    value: Decimal,
    source_unit: str | None,
    target_unit: str | None,
) -> tuple[Decimal, str | None, bool]:
    if target_unit is None:
        return value, None, False
    target = _normalize_unit(target_unit)
    if target in {"count", "iops", "percent", "day"}:
        return value, None, False
    if target == "gib":
        return _to_gib(value, source_unit)
    if target == "kib":
        return _to_kib(value, source_unit)
    if target == "gbps":
        return _to_gbps(value, source_unit)
    if target == "pps":
        return _to_pps(value, source_unit)
    return value, f"No conversion rule for target unit {target_unit}; retained numeric value.", True


def _to_gib(value: Decimal, source_unit: str | None) -> tuple[Decimal, str | None, bool]:
    if source_unit in {None, "", "gib"}:
        return value, None, False
    if source_unit in {"tib", "tb"}:
        return value * Decimal("1024"), "Converted TB/TiB-like source unit to GiB.", False
    if source_unit in {"mib", "mb"}:
        return value / Decimal("1024"), "Converted MB/MiB-like source unit to GiB.", False
    if source_unit in {"kib", "kb"}:
        return value / Decimal("1048576"), "Converted KB/KiB-like source unit to GiB.", False
    if source_unit == "gb":
        return value, "Legacy GB value retained as GiB-compatible; review decimal/binary ambiguity.", True
    return value, f"Unknown source storage unit {source_unit}; retained numeric value.", True


def _to_kib(value: Decimal, source_unit: str | None) -> tuple[Decimal, str | None, bool]:
    if source_unit in {None, "", "kib"}:
        return value, None, False
    if source_unit in {"mib", "mb"}:
        return value * Decimal("1024"), "Converted MB/MiB-like source unit to KiB.", False
    if source_unit in {"gib", "gb"}:
        return value * Decimal("1048576"), "Converted GB/GiB-like source unit to KiB.", False
    return value, f"Unknown source storage unit {source_unit}; retained numeric value.", True


def _to_gbps(value: Decimal, source_unit: str | None) -> tuple[Decimal, str | None, bool]:
    if source_unit in {None, "", "gbps", "gbit/s", "gbitps"}:
        return value, None, False
    if source_unit in {"mbps", "mbit/s", "mbitps"}:
        return value / Decimal("1000"), "Converted Mbps-like source unit to Gbps.", False
    if source_unit in {"kbps", "kbit/s", "kbitps"}:
        return value / Decimal("1000000"), "Converted Kbps-like source unit to Gbps.", False
    if source_unit in {"mb/s", "mib/s"}:
        return value * Decimal("8") / Decimal("1000"), "Converted MB/s-like source unit to Gbps.", True
    return value, f"Unknown source bandwidth unit {source_unit}; retained numeric value.", True


def _to_pps(value: Decimal, source_unit: str | None) -> tuple[Decimal, str | None, bool]:
    if source_unit in {None, "", "pps"}:
        return value, None, False
    if source_unit in {"10kpps", "10kpps.", "10kpps/s", "10kppspersecond"}:
        return value * Decimal("10000"), "Converted 10k PPS source unit to PPS.", False
    if source_unit in {"kpps"}:
        return value * Decimal("1000"), "Converted Kpps source unit to PPS.", False
    if source_unit in {"mpps"}:
        return value * Decimal("1000000"), "Converted Mpps source unit to PPS.", False
    return value, f"Unknown source packet-rate unit {source_unit}; retained numeric value.", True


def _parse_boolean(value: str) -> bool | None:
    text = value.strip().lower()
    if text in {"true", "yes", "supported", "support", "1"}:
        return True
    if text in {"false", "no", "unsupported", "not supported", "0"}:
        return False
    return None
