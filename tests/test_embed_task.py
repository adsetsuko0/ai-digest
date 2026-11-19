import pytest
from celery.exceptions import Retry
from sqlalchemy import select

import app.worker.tasks as tasks
from app.models import Article, Feed
from app.services.summarizer import LLMPermanentError, LLMUpstreamError


class StubEmbedder:
    model = "stub-embed"
    dim = 3

    def __init__(self):
        self.vector = [0.1, 0.2, 0.3]
        self.error = None
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.vector


@pytest.fixture
def factory(use_sync_db):
    return use_sync_db


@pytest.fixture
def embedder(monkeypatch):
    stub = StubEmbedder()
    monkeypatch.setattr(tasks, "get_embedder", lambda: stub)
    return stub


def add_article(factory, *, status="done", summary="The summary.") -> int:
    with factory() as session:
        feed = session.scalar(select(Feed).limit(1))
        if feed is None:
            feed = Feed(url="https://example.com/rss")
            session.add(feed)
            session.flush()
        article = Article(
            feed_id=feed.id,
            url="https://example.com/1",
            title="Title",
            content="Text",
            content_hash="hash",
            summary=summary,
            summary_status=status,
        )
        session.add(article)
        session.commit()
        return article.id


def stored_embedding(factory, article_id):
    with factory() as session:
        return session.scalar(select(Article.embedding).where(Article.id == article_id))


def test_embedding_is_saved(factory, embedder):
    article_id = add_article(factory)

    assert tasks.embed_article(article_id) == {"status": "done"}

    assert embedder.calls == ["Title\n\nThe summary."]
    assert stored_embedding(factory, article_id) == [0.1, 0.2, 0.3]


@pytest.mark.parametrize("status", ["pending", "failed", "skipped"])
def test_article_without_a_finished_summary_is_skipped(factory, embedder, status):
    article_id = add_article(factory, status=status, summary=None)

    assert tasks.embed_article(article_id) == {"status": "skipped"}
    assert embedder.calls == []


def test_missing_article_is_skipped(factory, embedder):
    assert tasks.embed_article(999) == {"status": "skipped"}


def test_temporary_error_is_retried(factory, embedder, monkeypatch):
    embedder.error = LLMUpstreamError("HTTP 503")
    delays = []

    def fake_retry(exc=None, countdown=None, **kwargs):
        delays.append(countdown)
        return Retry()

    monkeypatch.setattr(tasks.embed_article, "retry", fake_retry)
    article_id = add_article(factory)

    with pytest.raises(Retry):
        tasks.embed_article(article_id)

    assert delays == [60]
    assert stored_embedding(factory, article_id) is None


def test_exhausted_retries_leave_the_article_without_embedding(
    factory, embedder, monkeypatch
):
    embedder.error = LLMUpstreamError("HTTP 503")
    monkeypatch.setattr(tasks.embed_article, "max_retries", 0)
    article_id = add_article(factory)

    assert tasks.embed_article(article_id) == {"status": "failed"}
    assert stored_embedding(factory, article_id) is None


def test_permanent_error_is_not_retried(factory, embedder):
    embedder.error = LLMPermanentError("HTTP 401")
    article_id = add_article(factory)

    assert tasks.embed_article(article_id) == {"status": "failed"}


def test_unexpected_error_does_not_crash_the_task(factory, embedder):
    embedder.error = RuntimeError("boom")
    article_id = add_article(factory)

    assert tasks.embed_article(article_id) == {"status": "failed"}


def test_configuration_error_is_raised(factory, monkeypatch):
    def misconfigured():
        raise RuntimeError("EMBEDDING_PROVIDER=openai requires: LLM_API_KEY")

    monkeypatch.setattr(tasks, "get_embedder", misconfigured)
    article_id = add_article(factory)

    with pytest.raises(RuntimeError):
        tasks.embed_article(article_id)
