import json
from typing import Any


def inspect_json(content: bytes) -> tuple[str | None, dict[str, Any]]:
    try:
        parsed = json.loads(content.decode("utf-8"))
    except Exception as exc:
        return None, {"json_parse_success": False, "json_error": str(exc)}
    formatted = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)
    return formatted, {
        "json_parse_success": True,
        "json_top_level_type": type(parsed).__name__,
    }
