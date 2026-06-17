from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_map = dict(attrs)
        href = attrs_map.get("href")
        if not href:
            return
        absolute = urldefrag(urljoin(self.base_url, href))[0]
        if absolute.startswith(("http://", "https://")):
            self.links.append(absolute)


class ReadableTextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "pre",
        "section",
        "td",
        "th",
        "tr",
        "ul",
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in self.SKIP_TAGS:
            self._skip_depth += 1
        if lower in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if lower in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)


def extract_links(html: str, base_url: str) -> list[str]:
    parser = LinkExtractor(base_url)
    parser.feed(html)
    seen: set[str] = set()
    unique: list[str] = []
    for link in parser.links:
        if link not in seen:
            seen.add(link)
            unique.append(link)
    return unique


def extract_readable_text(html: str) -> str:
    parser = ReadableTextExtractor()
    parser.feed(html)
    text = unescape(" ".join(parser.parts))
    lines = []
    for line in text.splitlines():
        compact = " ".join(line.split())
        if compact:
            lines.append(compact)
    return "\n".join(lines)


class TargetBlockExtractor(HTMLParser):
    BLOCK_TAGS = ReadableTextExtractor.BLOCK_TAGS
    SKIP_TAGS = ReadableTextExtractor.SKIP_TAGS

    def __init__(self, site_key: str):
        super().__init__()
        self.site_key = site_key
        self.blocks: list[tuple[str, str]] = []
        self._label: str | None = None
        self._depth = 0
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        attrs_map = {key.lower(): value or "" for key, value in attrs}

        if self._label is None:
            label = self._target_label(lower, attrs_map)
            if label:
                self._label = label
                self._depth = 1
                self._parts = ["\n"]
                return

        if self._label is None:
            return

        self._depth += 1
        if lower in self.SKIP_TAGS:
            self._skip_depth += 1
        if lower in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._label is None:
            return

        lower = tag.lower()
        if lower in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if lower in self.BLOCK_TAGS:
            self._parts.append("\n")

        self._depth -= 1
        if self._depth <= 0:
            text = _normalize_text_parts(self._parts)
            if text:
                self.blocks.append((self._label, text))
            self._label = None
            self._parts = []
            self._skip_depth = 0

    def handle_data(self, data: str) -> None:
        if self._label is None or self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def _target_label(self, tag: str, attrs: dict[str, str]) -> str | None:
        classes = set(attrs.get("class", "").split())
        element_id = attrs.get("id", "")
        if self.site_key == "bobaedream":
            if tag == "div" and "bodyCont" in classes:
                return "post"
        if self.site_key == "ppomppu":
            if "board-contents" in classes:
                return "post"
            if element_id.startswith("commentContent_"):
                return "comment"
        return None


def extract_site_records(url: str, html: str) -> list[tuple[str, str]]:
    site_key = ""
    if "bobaedream.co.kr" in url:
        site_key = "bobaedream"
    elif "ppomppu.co.kr" in url:
        site_key = "ppomppu"

    if not site_key:
        text = extract_readable_text(html)
        return [("post", text)] if text else []

    parser = TargetBlockExtractor(site_key)
    parser.feed(html)
    if parser.blocks:
        return parser.blocks
    text = extract_readable_text(html)
    return [("post", text)] if text else []


def _normalize_text_parts(parts: list[str]) -> str:
    text = unescape(" ".join(parts))
    text = text.replace("\xa0", " ")
    lines = []
    for line in text.splitlines():
        compact = " ".join(line.split())
        if compact:
            lines.append(compact)
    return "\n".join(lines).strip()
