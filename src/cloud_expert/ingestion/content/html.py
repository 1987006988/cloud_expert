from bs4 import BeautifulSoup


def inspect_html(content: bytes, encoding: str | None = None) -> tuple[str, dict[str, object]]:
    text = content.decode(encoding or "utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    return text, {"title": title, "decoded_length": len(text)}
