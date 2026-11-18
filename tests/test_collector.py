import pytest
from sqlalchemy import func, select

from app.models.article import Article
from app.models.feed import Feed
from app.services import collector
from app.services.collector import normalize_url, store_entries, store_new_articles
from app.services.parser import ParsedEntry, _content_hash


def make_entry(url="https://example.com/1", title="Title", content="Body text"):
    return ParsedEntry(
        url=url,
        title=title,
        content=content,
        published_at=None,
        content_hash=_content_hash(title, content),
    )


def count_articles(session) -> int:
    return session.scalar(select(func.count()).select_from(Article))


@pytest.fixture
def feed(sync_session):
    feed = Feed(url="https://example.com/rss")
    sync_session.add(feed)
    sync_session.commit()
    return feed


def test_normalize_url_removes_utm_and_fragment():
    url = "HTTPS://Example.com/post?id=5&utm_source=tw&utm_medium=x#comments"
    assert normalize_url(url) == "https://example.com/post?id=5"


def test_inserts_new_entries(sync_session, feed):
    entries = [
        make_entry("https://example.com/1", "A", "text a"),
        make_entry("https://example.com/2", "B", "text b"),
    ]
    assert store_entries(sync_session, feed, entries) == 2
    assert count_articles(sync_session) == 2


def test_second_run_is_idempotent(sync_session, feed):
    entries = [make_entry()]
    assert store_entries(sync_session, feed, entries) == 1
    assert store_entries(sync_session, feed, entries) == 0
    assert count_articles(sync_session) == 1


def test_same_url_with_utm_is_duplicate(sync_session, feed):
    store_entries(sync_session, feed, [make_entry("https://example.com/1")])
    again = make_entry("https://example.com/1?utm_source=x#top", "Other", "other")
    assert store_entries(sync_session, feed, [again]) == 0


def test_same_text_under_other_url_is_skipped(sync_session, feed):
    store_entries(sync_session, feed, [make_entry("https://example.com/1")])
    copy = make_entry("https://example.com/mirror")
    assert store_entries(sync_session, feed, [copy]) == 0


def test_same_text_in_other_feed_is_stored(sync_session, feed):
    other = Feed(url="https://other.com/rss")
    sync_session.add(other)
    sync_session.commit()
    store_entries(sync_session, feed, [make_entry("https://example.com/1")])
    copy = make_entry("https://other.com/1")
    assert store_entries(sync_session, other, [copy]) == 1


def test_duplicates_inside_batch(sync_session, feed):
    entries = [make_entry("https://example.com/1"), make_entry("https://example.com/1")]
    assert store_entries(sync_session, feed, entries) == 1


def test_race_falls_back_to_one_by_one(sync_session, feed, monkeypatch):
    # "another worker" already inserted this URL
    store_entries(sync_session, feed, [make_entry("https://example.com/1")])
    sync_session.commit()
    # our existence check does not see it -> IntegrityError on insert
    monkeypatch.setattr(collector, "_drop_existing", lambda s, f, entries: entries)
    batch = [
        make_entry("https://example.com/1", "Dup", "dup text"),
        make_entry("https://example.com/2", "New", "new text"),
    ]
    assert store_entries(sync_session, feed, batch) == 1
    assert count_articles(sync_session) == 2


def test_store_new_articles_returns_articles_with_ids(sync_session, feed):
    entries = [
        make_entry("https://example.com/1", "A", "text a"),
        make_entry("https://example.com/2", "B", "text b"),
    ]

    articles = store_new_articles(sync_session, feed, entries)

    assert [a.url for a in articles] == [
        "https://example.com/1",
        "https://example.com/2",
    ]
    assert all(a.id for a in articles)
    assert store_new_articles(sync_session, feed, entries) == []
