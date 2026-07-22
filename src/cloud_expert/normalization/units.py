import re
from decimal import Decimal, InvalidOperation


def parse_decimal(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def normalize_memory_to_gib(raw_value: str) -> tuple[Decimal | None, str | None]:
    text = raw_value.strip()
    value = parse_decimal(text)
    if value is None:
        return None, None
    lower = text.lower()
    if "tib" in lower or "tb" in lower:
        return value * Decimal("1024"), "GiB"
    if "mib" in lower or "mb" in lower:
        return value / Decimal("1024"), "GiB"
    return value, "GiB"


def normalize_bandwidth_to_gbps(raw_value: str) -> tuple[Decimal | None, str | None]:
    value = parse_decimal(raw_value)
    if value is None:
        return None, None
    lower = raw_value.lower()
    if "mbps" in lower:
        return value / Decimal("1000"), "Gbps"
    return value, "Gbps"


def normalize_days(raw_value: str) -> tuple[int | None, str | None]:
    value = parse_decimal(raw_value)
    if value is None:
        return None, None
    return int(value), "day"
