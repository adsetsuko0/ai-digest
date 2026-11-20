import ipaddress

import httpx
import pytest
import respx
from celery.exceptions import Retry
from sqlalchemy import func, select

import app.worker.tasks as tasks
from app.core.config import settings
from app.models import Article, Feed
from app.services import fetcher
from app.services.fetcher import (
    ClientHTTPError,
    FetchResult,
    ResponseTooLarge,
    UnsafeURLError,
    UpstreamError,
)
from tests.helpers import metric_value

LAST_MODIFIED = "Wed, 01 Jan 2026 00:00:00 GMT"
RSS = b"""<rss version="2.0"><channel><title>Blog</title>
<item><title>Hello</title><link>https://example.com/1</link>
<description>First post</description></item>
<item><title>World</title><link>https://example.com/2</link>
<description>Second post</description></item>
</channel></rss>"""
OK = FetchResult(False, RSS, '"v1"', LAST_MODIFIED)


@pytest.fixture
def factory(use_sync_db):
    return use_sync_db


def add_feed(factory, **fields) -> int:
    url = fields.pop("url", "https://example.com/rss")
    with factory() as session:
        feed = Feed(url=url, **fields)
        session.add(feed)
        session.commit()
        return feed.id


def load_feed(factory, feed_id) -> Feed:
    with factory() as session:
        return session.get(Feed, feed_id)


def count_articles(factory) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(Article))


def stub_fetch(monkeypatch, result=None, error=None) -> list:
    """Replace the downloader; returns the list of (url, etag, last_modified) calls."""
    calls = []

    def fake(url, etag=None, last_modified=None):
        calls.append((url, etag, last_modified))
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(tasks, "fetch_feed_content", fake)
    return calls


def test_success_stores_articles_and_updates_feed(factory, monkeypatch):
    feed_id = add_feed(factory, consecutive_errors=2, last_error="old")
    stub_fetch(monkeypatch, OK)

    assert tasks.fetch_feed(feed_id) == {"status": "ok", "articles_new": 2}

    feed = load_feed(factory, feed_id)
    assert feed.title == "Blog"
    assert feed.etag == '"v1"'
    assert feed.last_modified == LAST_MODIFIED
    assert feed.consecutive_errors == 0
    assert feed.last_error is None
    assert feed.last_fetched_at is not None
    assert count_articles(factory) == 2


def test_not_modified_sends_validators_and_stores_nothing(factory, monkeypatch):
    feed_id = add_feed(factory, etag='"v1"', last_modified=LAST_MODIFIED)
    calls = stub_fetch(monkeypatch, FetchResult(True, b"", '"v1"', LAST_MODIFIED))

    assert tasks.fetch_feed(feed_id) == {"status": "not_modified", "articles_new": 0}

    assert calls == [("https://example.com/rss", '"v1"', LAST_MODIFIED)]
    feed = load_feed(factory, feed_id)
    assert feed.etag == '"v1"'
    assert feed.last_fetched_at is not None
    assert count_articles(factory) == 0


@pytest.mark.parametrize(
    "error",
    [UnsafeURLError("blocked"), ClientHTTPError("HTTP 404"), ResponseTooLarge("big")],
)
def test_permanent_error_is_counted(factory, monkeypatch, error):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, error=error)

    assert tasks.fetch_feed(feed_id) == {"status": "failed"}

    feed = load_feed(factory, feed_id)
    assert feed.consecutive_errors == 1
    assert feed.last_error == f"{type(error).__name__}: {error}"
    assert feed.is_active is True


def test_content_that_is_not_a_feed_counts_as_permanent_error(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, FetchResult(False, b"<html>nope</html>", None, None))

    assert tasks.fetch_feed(feed_id) == {"status": "failed"}
    assert "FeedParseError" in load_feed(factory, feed_id).last_error


def test_feed_is_disabled_on_fifth_consecutive_error(factory, monkeypatch):
    monkeypatch.setattr(settings, "FEED_MAX_CONSECUTIVE_ERRORS", 5)
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, error=ClientHTTPError("HTTP 404"))

    for _ in range(4):
        tasks.fetch_feed(feed_id)
    assert load_feed(factory, feed_id).is_active is True

    tasks.fetch_feed(feed_id)
    feed = load_feed(factory, feed_id)
    assert feed.consecutive_errors == 5
    assert feed.is_active is False


def test_success_after_errors_resets_the_counter(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, error=ClientHTTPError("HTTP 404"))
    tasks.fetch_feed(feed_id)
    tasks.fetch_feed(feed_id)
    assert load_feed(factory, feed_id).consecutive_errors == 2

    stub_fetch(monkeypatch, OK)
    tasks.fetch_feed(feed_id)

    feed = load_feed(factory, feed_id)
    assert feed.consecutive_errors == 0
    assert feed.last_error is None


def test_last_error_is_truncated_to_500_characters(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, error=ClientHTTPError("x" * 1000))

    tasks.fetch_feed(feed_id)

    assert len(load_feed(factory, feed_id).last_error) == 500


def test_inactive_feed_is_skipped(factory, monkeypatch):
    feed_id = add_feed(factory, is_active=False)
    calls = stub_fetch(monkeypatch, OK)

    assert tasks.fetch_feed(feed_id) == {"status": "skipped"}
    assert calls == []


def test_missing_feed_is_skipped(factory, monkeypatch):
    calls = stub_fetch(monkeypatch, OK)

    assert tasks.fetch_feed(999) == {"status": "skipped"}
    assert calls == []


def test_temporary_error_is_retried_with_delay_and_not_counted(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, error=UpstreamError("HTTP 503"))
    retries = []

    def fake_retry(exc=None, countdown=None, **kwargs):
        retries.append(countdown)
        return Retry()

    monkeypatch.setattr(tasks.fetch_feed, "retry", fake_retry)

    with pytest.raises(Retry):
        tasks.fetch_feed(feed_id)

    assert retries == [60]
    assert load_feed(factory, feed_id).consecutive_errors == 0


def test_temporary_error_counts_when_retries_are_exhausted(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, error=UpstreamError("HTTP 503"))
    monkeypatch.setattr(tasks.fetch_feed, "max_retries", 0)

    assert tasks.fetch_feed(feed_id) == {"status": "failed"}
    assert load_feed(factory, feed_id).consecutive_errors == 1


def test_unexpected_error_is_counted_too(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, OK)

    def boom(content):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "parse_feed", boom)

    assert tasks.fetch_feed(feed_id) == {"status": "failed"}
    feed = load_feed(factory, feed_id)
    assert feed.consecutive_errors == 1
    assert feed.last_error == "RuntimeError: boom"


def test_host_resolving_to_private_ip_is_blocked(factory, monkeypatch):
    # the real fetcher runs here, only DNS is faked (like localtest.me -> 127.0.0.1)
    monkeypatch.setattr(
        fetcher, "resolve_host_ips", lambda host: [ipaddress.ip_address("127.0.0.1")]
    )
    feed_id = add_feed(factory, url="https://localtest.me/rss")

    assert tasks.fetch_feed(feed_id) == {"status": "failed"}
    assert "UnsafeURLError" in load_feed(factory, feed_id).last_error


def test_full_pipeline_second_run_adds_nothing(factory, monkeypatch):
    monkeypatch.setattr(
        fetcher,
        "resolve_host_ips",
        lambda host: [ipaddress.ip_address("93.184.216.34")],
    )
    feed_id = add_feed(factory)
    with respx.mock() as router:
        router.get("https://example.com/rss").mock(
            return_value=httpx.Response(200, content=RSS)
        )
        assert tasks.fetch_feed(feed_id) == {"status": "ok", "articles_new": 2}
        assert tasks.fetch_feed(feed_id) == {"status": "ok", "articles_new": 0}
    assert count_articles(factory) == 2


def test_new_articles_are_queued_for_summaries(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, OK)
    queued = []
    monkeypatch.setattr(tasks.summarize_article, "delay", queued.append)

    tasks.fetch_feed(feed_id)

    assert len(queued) == 2
    with factory() as session:
        ids = set(session.scalars(select(Article.id)))
    assert set(queued) == ids

    queued.clear()
    tasks.fetch_feed(feed_id)  # the same articles again
    assert queued == []


def test_broker_failure_does_not_break_feed_collection(factory, monkeypatch):
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, OK)
    attempts = []

    def broken_delay(article_id):
        attempts.append(article_id)
        raise ConnectionError("broker is down")

    monkeypatch.setattr(tasks.summarize_article, "delay", broken_delay)

    assert tasks.fetch_feed(feed_id) == {"status": "ok", "articles_new": 2}
    assert len(attempts) == 1  # gave up after the first failure
    assert count_articles(factory) == 2


def test_collected_articles_are_counted(factory, monkeypatch):
    before = metric_value("articles_fetched_total")
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, OK)

    tasks.fetch_feed(feed_id)

    assert metric_value("articles_fetched_total") == before + 2


@pytest.mark.parametrize(
    ("result", "error", "kind"),
    [
        (None, ClientHTTPError("HTTP 404"), "permanent"),
        (FetchResult(False, b"<html>nope</html>", None, None), None, "parse"),
    ],
)
def test_fetch_errors_are_counted_by_kind(factory, monkeypatch, result, error, kind):
    before = metric_value("fetch_errors_total", kind=kind)
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, result, error)

    tasks.fetch_feed(feed_id)

    assert metric_value("fetch_errors_total", kind=kind) == before + 1


def test_temporary_error_is_counted_even_when_retried(factory, monkeypatch):
    before = metric_value("fetch_errors_total", kind="temporary")
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, error=UpstreamError("HTTP 503"))
    monkeypatch.setattr(tasks.fetch_feed, "retry", lambda **kwargs: Retry())

    with pytest.raises(Retry):
        tasks.fetch_feed(feed_id)

    assert metric_value("fetch_errors_total", kind="temporary") == before + 1


def test_unexpected_error_is_counted(factory, monkeypatch):
    before = metric_value("fetch_errors_total", kind="unexpected")
    feed_id = add_feed(factory)
    stub_fetch(monkeypatch, OK)

    def boom(content):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "parse_feed", boom)
    tasks.fetch_feed(feed_id)

    assert metric_value("fetch_errors_total", kind="unexpected") == before + 1
