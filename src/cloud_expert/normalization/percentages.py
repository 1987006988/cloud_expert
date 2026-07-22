import re
from decimal import Decimal, InvalidOperation


def normalize_percentage(raw_value: str) -> Decimal | None:
    text = raw_value.strip()
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None
