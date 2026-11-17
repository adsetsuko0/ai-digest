import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Article, Feed
from app.models.article import SummaryStatus


async def test_new_feed_has_clean_fetch_state(db_session):
    feed = Feed(url="https://example.com/rss")
    db_session.add(feed)
    await db_session.commit()
    await db_session.refresh(feed)

    assert feed.consecutive_errors == 0
    assert feed.etag is None
    assert feed.last_modified is None
    assert feed.last_error is None


async def test_new_article_gets_default_summary_fields(db_session):
    feed = Feed(url="https://example.com/rss")
    db_session.add(feed)
    await db_session.flush()
    article = Article(
        feed_id=feed.id, url="https://example.com/a", content_hash="a" * 64
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    assert article.summary_status == SummaryStatus.PENDING
    assert article.fetched_at is not None
    assert article.summary_model is None
    assert article.tokens_used is None


async def test_unknown_summary_status_is_rejected(db_session):
    feed = Feed(url="https://example.com/rss")
    db_session.add(feed)
    await db_session.flush()
    db_session.add(
        Article(
            feed_id=feed.id,
            url="https://example.com/a",
            content_hash="a" * 64,
            summary_status="weird",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
