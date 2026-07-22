from typing import Any

from cloud_expert.ingestion.content.html import inspect_html
from cloud_expert.ingestion.content.json_content import inspect_json
from cloud_expert.ingestion.content.pdf import inspect_pdf


def inspect_content(
    content_type: str, content: bytes, encoding: str | None = None
) -> tuple[bytes | None, dict[str, Any]]:
    media_type = content_type.split(";", 1)[0].lower()
    if media_type == "text/html":
        decoded, metadata = inspect_html(content, encoding)
        return decoded.encode("utf-8"), metadata
    if media_type == "application/json":
        formatted, metadata = inspect_json(content)
        return formatted.encode("utf-8") if formatted is not None else None, metadata
    if media_type == "application/pdf":
        return None, inspect_pdf(content)
    return None, {}
