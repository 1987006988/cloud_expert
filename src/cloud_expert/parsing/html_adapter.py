from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class HtmlTable:
    caption: str | None
    headers: list[str]
    rows: list[list[str]]
    locator: str


@dataclass(frozen=True)
class HtmlDocument:
    title: str
    text: str
    soup: BeautifulSoup

    def first_heading(self) -> str:
        heading = self.soup.find(["h1", "h2"])
        if heading:
            return " ".join(heading.get_text(" ", strip=True).split())
        return self.title

    def paragraphs_containing(self, *keywords: str) -> list[tuple[str, str]]:
        matches: list[tuple[str, str]] = []
        for index, node in enumerate(self.soup.find_all(["p", "li", "td", "th", "div"])):
            text = " ".join(node.get_text(" ", strip=True).split())
            if not text or len(text) < 8:
                continue
            if node.name == "div" and len(text) > 1200:
                continue
            if any(keyword in text for keyword in keywords):
                matches.append((f"html:text[{index}]", text))
        return matches

    def tables(self) -> list[HtmlTable]:
        tables: list[HtmlTable] = []
        for table_index, table in enumerate(self.soup.find_all("table")):
            caption_node = table.find("caption")
            caption = (
                " ".join(caption_node.get_text(" ", strip=True).split()) if caption_node else None
            )
            table_rows: list[list[str]] = []
            for row in table.find_all("tr"):
                cells = [
                    " ".join(cell.get_text(" ", strip=True).split())
                    for cell in row.find_all(["th", "td"])
                ]
                if any(cells):
                    table_rows.append(cells)
            if not table_rows:
                continue
            headers = table_rows[0]
            rows = table_rows[1:] if len(table_rows) > 1 else []
            tables.append(
                HtmlTable(
                    caption=caption,
                    headers=headers,
                    rows=rows,
                    locator=f"html:table[{table_index}]",
                )
            )
        return tables


def load_html_document(path: Path, encoding: str | None = "utf-8") -> HtmlDocument:
    content = path.read_bytes()
    soup = BeautifulSoup(content, "html.parser", from_encoding=encoding)
    title_node = soup.find("title")
    title = (
        " ".join(title_node.get_text(" ", strip=True).split())
        if title_node
        else "Untitled HTML document"
    )
    text = " ".join(soup.get_text(" ", strip=True).split())
    return HtmlDocument(title=title, text=text, soup=soup)
