import datetime

import pytest

from app.services.parser import (
    FeedParseError,
    _is_http_url,
    _parse_raw_date,
    parse_feed,
)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Blog</title>
<item>
  <title>Hello</title><link>https://example.com/1</link>
  <description>&lt;p&gt;Some &lt;b&gt;text&lt;/b&gt;&lt;/p&gt;</description>
  <pubDate>Wed, 01 Jan 2026 10:00:00 +0300</pubDate>
</item>
</channel></rss>"""


def test_rss_fields_and_utc_date():
    feed = parse_feed(RSS)
    assert feed.title == "Blog"
    entry = feed.entries[0]
    assert entry.url == "https://example.com/1"
    assert entry.content == "Some text"
    assert entry.published_at == datetime.datetime(
        2026, 1, 1, 7, 0, tzinfo=datetime.UTC
    )


def test_broken_xml_raises():
    with pytest.raises(FeedParseError):
        parse_feed(b"<rss><channel><item>")


def test_entry_without_link_is_skipped():
    data = RSS.replace(b"<link>https://example.com/1</link>", b"")
    assert parse_feed(data).entries == []


def rss_item(link="https://example.com/1", extra=""):
    return f"<item><title>T</title><link>{link}</link>{extra}</item>"


def rss(*items: str) -> bytes:
    body = "".join(items)
    return (
        f'<rss version="2.0"><channel><title>Blog</title>{body}</channel></rss>'
    ).encode()


ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Blog</title>
<entry>
  <title>Post</title><link href="https://example.com/a"/><id>1</id>
  <updated>2026-01-01T10:00:00Z</updated>
  <content type="html">&lt;p&gt;Hello &lt;i&gt;world&lt;/i&gt;&lt;/p&gt;</content>
</entry></feed>"""


def test_atom_feed():
    feed = parse_feed(ATOM)
    assert feed.title == "Atom Blog"
    entry = feed.entries[0]
    assert entry.url == "https://example.com/a"
    assert entry.content == "Hello world"
    assert entry.published_at == datetime.datetime(
        2026, 1, 1, 10, 0, tzinfo=datetime.UTC
    )


def test_date_without_timezone_is_utc():
    data = rss(rss_item(extra="<pubDate>Wed, 01 Jan 2026 10:00:00</pubDate>"))
    published = parse_feed(data).entries[0].published_at
    assert published == datetime.datetime(2026, 1, 1, 10, 0, tzinfo=datetime.UTC)
    assert published.tzinfo is not None


def test_entry_without_date_has_none():
    assert parse_feed(rss(rss_item())).entries[0].published_at is None


@pytest.mark.parametrize("link", ["javascript:alert(1)", "ftp://example.com/f"])
def test_non_http_links_are_skipped(link):
    assert parse_feed(rss(rss_item(link))).entries == []


def test_script_content_is_removed():
    desc = "<description>&lt;script&gt;evil()&lt;/script&gt;visible</description>"
    assert parse_feed(rss(rss_item(extra=desc))).entries[0].content == "visible"


def test_long_title_and_content_are_truncated():
    item = (
        f"<item><title>{'t' * 600}</title><link>https://example.com/1</link>"
        f"<description>{'a' * 25000}</description></item>"
    )
    entry = parse_feed(rss(item)).entries[0]
    assert len(entry.title) == 500
    assert len(entry.content) == 20000


def test_only_100_newest_entries_are_kept():
    entries = "".join(
        f"<entry><title>T{i}</title><link href='https://example.com/{i}'/>"
        f"<id>{i}</id><updated>2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z</updated>"
        f"<summary>text {i}</summary></entry>"
        for i in range(150)
    )
    data = (
        f'<feed xmlns="http://www.w3.org/2005/Atom"><title>X</title>{entries}</feed>'
    ).encode()
    result = parse_feed(data).entries
    assert len(result) == 100
    assert result[0].url == "https://example.com/149"  # the newest first


def test_html_page_instead_of_feed_raises():
    with pytest.raises(FeedParseError):
        parse_feed(b"<html><body><h1>Not a feed</h1></body></html>")


def test_valid_empty_feed_returns_no_entries():
    feed = parse_feed(
        b'<rss version="2.0"><channel><title>Empty</title></channel></rss>'
    )
    assert feed.title == "Empty"
    assert feed.entries == []


def test_garbage_date_gives_none():
    data = rss(rss_item(extra="<pubDate>not a date</pubDate>"))
    assert parse_feed(data).entries[0].published_at is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("not a date", None),
        (
            "Wed, 01 Jan 2026 10:00:00",
            datetime.datetime(2026, 1, 1, 10, tzinfo=datetime.UTC),
        ),
        (
            "Wed, 01 Jan 2026 10:00:00 +0300",
            datetime.datetime(2026, 1, 1, 7, tzinfo=datetime.UTC),
        ),
        ("2026-01-01T10:00:00", datetime.datetime(2026, 1, 1, 10, tzinfo=datetime.UTC)),
        (
            "2026-01-01T10:00:00+03:00",
            datetime.datetime(2026, 1, 1, 7, tzinfo=datetime.UTC),
        ),
    ],
)
def test_parse_raw_date(raw, expected):
    assert _parse_raw_date(raw) == expected


def test_is_http_url_rejects_malformed():
    assert _is_http_url("http://[broken") is False
    assert _is_http_url("https://example.com") is True
