import datetime
import hashlib
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import feedparser
import pytest

MAX_ENTRIES = 100
MAX_TITLE_LENGTH = 500
MAX_CONTENT_LENGTH = 20_000
ALLOWED_SCHEMES = {"http", "https"}
_SKIPPED_TAGS = {"script", "style"}
_WHITESPACE = re.compile(r"\s+")


class FeedParseError(Exception):
    """The downloaded content is not a valid feed."""


@dataclass(frozen=True)
class ParsedEntry:
    url: str
    title: str
    content: str
    published_at: datetime.datetime | None  # tz-aware, UTC
    content_hash: str


@dataclass(frozen=True)
class ParsedFeed:
    title: str | None
    entries: list[ParsedEntry]


class _TextExtractor(HTMLParser):
    """Collects the text of an HTML fragment, ignoring <script> and <style>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # &amp; -> &, &nbsp; -> space
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _normalize_spaces(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _strip_html(raw: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(raw)
    extractor.close()
    return _normalize_spaces(extractor.get_text())


def _is_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in ALLOWED_SCHEMES and bool(parts.netloc)


def _parse_raw_date(raw: str) -> datetime.datetime | None:
    """Fallback for dates feedparser could not parse (e.g. no time zone)."""
    raw = raw.strip()
    if not raw:
        return None
    for parse in (parsedate_to_datetime, datetime.datetime.fromisoformat):
        try:
            value = parse(raw)
        except (ValueError, TypeError):
            continue
        if value.tzinfo is None:  # no time zone -> treat as UTC
            return value.replace(tzinfo=datetime.UTC)
        return value.astimezone(datetime.UTC)
    return None


def _extract_date(entry: feedparser.FeedParserDict) -> datetime.datetime | None:
    # feedparser already converts the dates it understands to UTC
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime.datetime(*parsed[:6], tzinfo=datetime.UTC)
        except (ValueError, TypeError):
            return None
    # feedparser gave up (for example the date has no time zone): try ourselves
    return _parse_raw_date(entry.get("published") or entry.get("updated") or "")


def _content_hash(title: str, content: str) -> str:
    normalized = (
        f"{_normalize_spaces(title).lower()}\n{_normalize_spaces(content).lower()}"
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_entry(entry: feedparser.FeedParserDict) -> ParsedEntry | None:
    url = (entry.get("link") or "").strip()
    if not _is_http_url(url):
        return None

    title = _strip_html(entry.get("title") or "")[:MAX_TITLE_LENGTH]

    contents = entry.get("content")
    raw = contents[0].get("value", "") if contents else entry.get("summary", "")
    text = _strip_html(raw or "")[:MAX_CONTENT_LENGTH]

    return ParsedEntry(
        url=url,
        title=title,
        content=text,
        published_at=_extract_date(entry),
        content_hash=_content_hash(title, text),
    )


def parse_feed(content: bytes) -> ParsedFeed:
    # always pass bytes: feedparser treats a str that looks like a URL
    # as an address and downloads it itself, bypassing our SSRF checks
    result = feedparser.parse(content)

    entries = [e for e in map(_parse_entry, result.entries) if e is not None]

    # no usable entries AND the content looks broken or is not a feed at all
    if not entries and (result.bozo or not result.get("version")):
        reason = str(result.get("bozo_exception", "no feed found"))[:200]
        raise FeedParseError(f"Could not parse feed: {reason}")

    # newest first, entries without a date go last (the sort is stable)
    oldest = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    entries.sort(key=lambda e: e.published_at or oldest, reverse=True)

    feed_title = _strip_html(result.feed.get("title") or "")[:MAX_TITLE_LENGTH]
    return ParsedFeed(title=feed_title or None, entries=entries[:MAX_ENTRIES])


def test_html_page_instead_of_feed_raises():
    with pytest.raises(FeedParseError):
        parse_feed(b"<html><body><h1>Not a feed</h1></body></html>")


def test_valid_empty_feed_returns_no_entries():
    data = b'<rss version="2.0"><channel><title>Empty</title></channel></rss>'
    feed = parse_feed(data)
    assert feed.title == "Empty"
    assert feed.entries == []
