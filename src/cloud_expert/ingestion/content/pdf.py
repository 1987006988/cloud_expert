from io import BytesIO

from pypdf import PdfReader


def inspect_pdf(content: bytes) -> dict[str, object]:
    if not content.startswith(b"%PDF"):
        msg = "content does not start with PDF magic bytes"
        raise ValueError(msg)
    reader = PdfReader(BytesIO(content))
    return {
        "pdf_parse_success": True,
        "pdf_page_count": len(reader.pages),
        "is_pdf_encrypted": reader.is_encrypted,
        "pdf_metadata": {key: str(value) for key, value in (reader.metadata or {}).items()},
    }
