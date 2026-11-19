import hashlib

import pytest
import redis
from celery.exceptions import Retry
from sqlalchemy import select

import app.worker.tasks as tasks
from app.core.config import settings
from app.models import Article, Feed
from app.services.summarizer import LLMPermanentError, LLMUpstreamError, SummaryResult
from app.services.token_budget import daily_key


class StubSummarizer:
    model = "stub-model"

    def __init__(self):
        self.result = SummaryResult("Short summary.", 40)
        self.error = None
        self.calls = []

    def summarize(self, text):
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def factory(use_sync_db):
    return use_sync_db


@pytest.fixture
def stub(monkeypatch):
    stub = StubSummarizer()
    monkeypatch.setattr(tasks, "get_summarizer", lambda: stub)
    return stub


def add_article(factory, *, url="https://example.com/1", **fields) -> int:
    fields.setdefault("title", "Title")
    fields.setdefault("content", "First sentence. Second sentence.")
    fields.setdefault("content_hash", hashlib.sha256(url.encode()).hexdigest())
    with factory() as session:
        feed = session.scalar(select(Feed).limit(1))
        if feed is None:
            feed = Feed(url="https://example.com/rss")
            session.add(feed)
            session.flush()
        article = Article(feed_id=feed.id, url=url, **fields)
        session.add(article)
        session.commit()
        return article.id


def load_article(factory, article_id) -> Article:
    with factory() as session:
        return session.get(Article, article_id)


# --- success and cache ------------------------------------------------------------


def test_success_saves_summary_and_counts_tokens(factory, stub, fake_redis):
    article_id = add_article(factory)

    result = tasks.summarize_article(article_id)

    assert result == {"status": "done", "cache_hit": False, "tokens": 40}
    article = load_article(factory, article_id)
    assert article.summary == "Short summary."
    assert article.summary_model == "stub-model"
    assert article.tokens_used == 40
    assert article.summary_status == "done"
    assert fake_redis.get(daily_key()) == "40"
    assert "Title" in stub.calls[0] and "First sentence." in stub.calls[0]


def test_cache_hit_reuses_summary_without_calling_the_llm(factory, stub, fake_redis):
    add_article(
        factory,
        url="https://example.com/old",
        content_hash="same-hash",
        summary="Cached summary.",
        summary_model="old-model",
        summary_status="done",
    )
    article_id = add_article(
        factory, url="https://example.com/new", content_hash="same-hash"
    )

    result = tasks.summarize_article(article_id)

    assert result == {"status": "done", "cache_hit": True}
    assert stub.calls == []
    article = load_article(factory, article_id)
    assert article.summary == "Cached summary."
    assert article.summary_model == "old-model"
    assert article.tokens_used == 0
    assert fake_redis.get(daily_key()) is None  # nothing was spent


def test_cache_ignores_articles_without_a_finished_summary(factory, stub, fake_redis):
    add_article(
        factory,
        url="https://example.com/old",
        content_hash="same-hash",
        summary_status="failed",
    )
    article_id = add_article(
        factory, url="https://example.com/new", content_hash="same-hash"
    )

    tasks.summarize_article(article_id)

    assert len(stub.calls) == 1


def test_article_that_is_not_pending_is_left_alone(factory, stub, fake_redis):
    article_id = add_article(factory, summary="Done before.", summary_status="done")

    assert tasks.summarize_article(article_id) == {"status": "not_pending"}
    assert stub.calls == []
    assert load_article(factory, article_id).summary == "Done before."


def test_missing_article_is_ignored(factory, stub, fake_redis):
    assert tasks.summarize_article(999) == {"status": "not_pending"}
    assert stub.calls == []


def test_article_without_text_is_skipped(factory, stub, fake_redis):
    article_id = add_article(factory, title="  ", content="")

    assert tasks.summarize_article(article_id) == {"status": "skipped"}
    assert stub.calls == []
    assert load_article(factory, article_id).summary_status == "skipped"


# --- budget -----------------------------------------------------------------------


def test_article_is_skipped_when_the_daily_budget_is_spent(
    factory, stub, fake_redis, monkeypatch
):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_BUDGET", 100)
    fake_redis.set(daily_key(), 100)
    article_id = add_article(factory)

    assert tasks.summarize_article(article_id) == {"status": "skipped"}

    assert stub.calls == []
    assert load_article(factory, article_id).summary_status == "skipped"


def test_article_is_summarized_while_budget_remains(
    factory, stub, fake_redis, monkeypatch
):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_BUDGET", 100)
    fake_redis.set(daily_key(), 99)
    article_id = add_article(factory)

    assert tasks.summarize_article(article_id)["status"] == "done"
    assert fake_redis.get(daily_key()) == "139"  # the last article may overshoot


# --- errors -----------------------------------------------------------------------


def test_permanent_llm_error_marks_the_article_failed(factory, stub, fake_redis):
    stub.error = LLMPermanentError("HTTP 401")
    article_id = add_article(factory)

    assert tasks.summarize_article(article_id) == {"status": "failed"}
    assert load_article(factory, article_id).summary_status == "failed"
    assert fake_redis.get(daily_key()) is None


def test_temporary_error_is_retried_and_the_article_stays_pending(
    factory, stub, fake_redis, monkeypatch
):
    stub.error = LLMUpstreamError("HTTP 503")
    article_id = add_article(factory)
    delays = []

    def fake_retry(exc=None, countdown=None, **kwargs):
        delays.append(countdown)
        return Retry()

    monkeypatch.setattr(tasks.summarize_article, "retry", fake_retry)

    with pytest.raises(Retry):
        tasks.summarize_article(article_id)

    assert delays == [60]
    assert load_article(factory, article_id).summary_status == "pending"


def test_temporary_error_fails_the_article_when_retries_are_exhausted(
    factory, stub, fake_redis, monkeypatch
):
    stub.error = LLMUpstreamError("HTTP 503")
    monkeypatch.setattr(tasks.summarize_article, "max_retries", 0)
    article_id = add_article(factory)

    assert tasks.summarize_article(article_id) == {"status": "failed"}
    assert load_article(factory, article_id).summary_status == "failed"


def test_unexpected_error_marks_the_article_failed(factory, stub, fake_redis):
    stub.error = RuntimeError("boom")
    article_id = add_article(factory)

    assert tasks.summarize_article(article_id) == {"status": "failed"}
    assert load_article(factory, article_id).summary_status == "failed"


def test_redis_outage_is_a_temporary_error(factory, stub, monkeypatch):
    class BrokenRedis:
        def get(self, *args, **kwargs):
            raise redis.ConnectionError("down")

    monkeypatch.setattr(tasks, "get_redis", lambda: BrokenRedis())
    monkeypatch.setattr(tasks.summarize_article, "retry", lambda **kwargs: Retry())
    article_id = add_article(factory)

    with pytest.raises(Retry):
        tasks.summarize_article(article_id)

    assert stub.calls == []  # no budget information, so no spending
    assert load_article(factory, article_id).summary_status == "pending"


def test_failed_token_accounting_does_not_lose_the_summary(
    factory, stub, fake_redis, monkeypatch
):
    def broken_add_tokens(client, tokens):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(tasks, "add_tokens", broken_add_tokens)
    article_id = add_article(factory)

    assert tasks.summarize_article(article_id)["status"] == "done"
    assert load_article(factory, article_id).summary == "Short summary."


def test_configuration_error_is_raised_and_the_article_stays_pending(
    factory, fake_redis, monkeypatch
):
    def misconfigured():
        raise RuntimeError("LLM_PROVIDER=openai requires: LLM_API_KEY")

    monkeypatch.setattr(tasks, "get_summarizer", misconfigured)
    article_id = add_article(factory)

    with pytest.raises(RuntimeError):
        tasks.summarize_article(article_id)

    assert load_article(factory, article_id).summary_status == "pending"


def test_embedding_is_queued_after_a_summary(factory, stub, fake_redis, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.embed_article, "delay", queued.append)
    article_id = add_article(factory)

    tasks.summarize_article(article_id)

    assert queued == [article_id]


def test_embedding_is_queued_after_a_cache_hit(factory, stub, fake_redis, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.embed_article, "delay", queued.append)
    add_article(
        factory,
        url="https://example.com/old",
        content_hash="same-hash",
        summary="Cached summary.",
        summary_model="old-model",
        summary_status="done",
    )
    article_id = add_article(
        factory, url="https://example.com/new", content_hash="same-hash"
    )

    tasks.summarize_article(article_id)

    assert queued == [article_id]


def test_no_embedding_without_a_summary(factory, stub, fake_redis, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.embed_article, "delay", queued.append)
    stub.error = LLMPermanentError("HTTP 401")

    tasks.summarize_article(add_article(factory))

    assert queued == []


def test_embedding_enqueue_failure_does_not_lose_the_summary(
    factory, stub, fake_redis, monkeypatch
):
    def broken_delay(article_id):
        raise ConnectionError("broker is down")

    monkeypatch.setattr(tasks.embed_article, "delay", broken_delay)
    article_id = add_article(factory)

    assert tasks.summarize_article(article_id)["status"] == "done"
    assert load_article(factory, article_id).summary == "Short summary."
