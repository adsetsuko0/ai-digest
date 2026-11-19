import datetime
import random
import time

import redis
import structlog
from sqlalchemy import exists, select

from app.core.config import settings
from app.core.redis import get_redis
from app.db.sync import session_scope
from app.models import Article, Feed, UserFeed
from app.models.article import SummaryStatus
from app.services.collector import store_new_articles
from app.services.embedder import get_embedder
from app.services.fetcher import FetchError, fetch_feed_content
from app.services.parser import FeedParseError, parse_feed
from app.services.summarizer import LLMError, get_summarizer
from app.services.token_budget import add_tokens, budget_exceeded
from app.worker.celery_app import celery_app

logger = structlog.get_logger(__name__)

MAX_ERROR_LENGTH = 500
MAX_START_DELAY_SECONDS = 60


def retry_delay(retries: int) -> int:
    """Growing delay between attempts: 60, 240, 960 seconds."""
    return 60 * 4**retries


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@celery_app.task(name="app.worker.tasks.ping")
def ping() -> str:
    return "pong"


# --- feed collection ------------------------------------------------------------


def _record_failure(feed_id: int, exc: Exception, log, started: float) -> None:
    message = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
    with session_scope() as session:
        feed = session.get(Feed, feed_id)
        if feed is None:
            return
        feed.consecutive_errors += 1
        feed.last_error = message
        disabled = feed.consecutive_errors >= settings.FEED_MAX_CONSECUTIVE_ERRORS
        if disabled:
            feed.is_active = False
        errors = feed.consecutive_errors
    log.warning(
        "fetch_feed",
        status="failed",
        error=message,
        consecutive_errors=errors,
        disabled=disabled,
        duration_ms=_ms(started),
    )


def _enqueue_summaries(article_ids: list[int], log) -> None:
    for position, article_id in enumerate(article_ids):
        try:
            summarize_article.delay(article_id)
        except Exception:
            # The articles stay "pending". Do not try the rest: with the broker
            # down every attempt would wait for a connection timeout.
            log.exception(
                "summarize_enqueue_failed",
                article_id=article_id,
                not_enqueued=len(article_ids) - position,
            )
            return


@celery_app.task(bind=True, max_retries=3, name="app.worker.tasks.fetch_feed")
def fetch_feed(self, feed_id: int) -> dict:
    started = time.monotonic()
    log = logger.bind(feed_id=feed_id)

    # 1) read what we need and release the DB connection before the network call
    with session_scope() as session:
        feed = session.get(Feed, feed_id)
        if feed is None or not feed.is_active:
            log.info("fetch_feed", status="skipped", duration_ms=_ms(started))
            return {"status": "skipped"}
        url, etag, last_modified = feed.url, feed.etag, feed.last_modified
    log = log.bind(url=url)

    # 2) download and parse, no DB connection is held meanwhile
    try:
        result = fetch_feed_content(url, etag, last_modified)
        parsed = None if result.not_modified else parse_feed(result.content)
    except (FetchError, FeedParseError) as exc:
        retryable = isinstance(exc, FetchError) and exc.retryable
        if retryable and self.request.retries < self.max_retries:
            log.warning(
                "fetch_feed",
                status="retry",
                error=str(exc),
                attempt=self.request.retries + 1,
                duration_ms=_ms(started),
            )
            raise self.retry(
                exc=exc, countdown=retry_delay(self.request.retries)
            ) from exc
        # permanent error, or a temporary one that did not go away after all retries
        _record_failure(feed_id, exc, log, started)
        return {"status": "failed"}
    except (
        Exception
    ) as exc:  # last line of defense: a broken feed must not loop forever
        log.exception("fetch_feed_unexpected_error")
        _record_failure(feed_id, exc, log, started)
        return {"status": "failed"}

    # 3) save the result in one transaction
    new_ids: list[int] = []
    with session_scope() as session:
        feed = session.get(Feed, feed_id)
        if feed is None:
            return {"status": "skipped"}
        if parsed is not None:
            new_ids = [a.id for a in store_new_articles(session, feed, parsed.entries)]
        if parsed is not None and parsed.title:
            feed.title = parsed.title
        feed.etag = result.etag
        feed.last_modified = result.last_modified
        feed.consecutive_errors = 0
        feed.last_error = None
        feed.last_fetched_at = datetime.datetime.now(datetime.UTC)

    # only after the commit: a summary task must be able to find its article
    _enqueue_summaries(new_ids, log)

    new = len(new_ids)
    status = "not_modified" if result.not_modified else "ok"
    log.info("fetch_feed", status=status, articles_new=new, duration_ms=_ms(started))
    return {"status": status, "articles_new": new}


@celery_app.task(name="app.worker.tasks.fetch_all_feeds")
def fetch_all_feeds() -> int:
    with session_scope() as session:
        feed_ids = list(
            session.scalars(
                select(Feed.id).where(
                    Feed.is_active.is_(True),
                    exists().where(UserFeed.feed_id == Feed.id),
                )
            )
        )
    for feed_id in feed_ids:
        fetch_feed.apply_async(
            args=[feed_id], countdown=random.randint(0, MAX_START_DELAY_SECONDS)
        )
    logger.info("fetch_all_feeds", feeds_scheduled=len(feed_ids))
    return len(feed_ids)


# --- summaries and embeddings -----------------------------------------------------


def _article_input(title: str | None, content: str | None) -> str:
    parts = (title, content)
    return "\n\n".join(part for part in parts if part and part.strip())


def _set_final_status(article_id: int, status: SummaryStatus) -> None:
    """Set skipped/failed, but never overwrite an article that is already done."""
    with session_scope() as session:
        article = session.get(Article, article_id)
        if article is not None and article.summary_status == SummaryStatus.PENDING:
            article.summary_status = status.value


def _fail_article(article_id: int, exc: Exception, log, started: float) -> None:
    _set_final_status(article_id, SummaryStatus.FAILED)
    log.warning(
        "summarize_article",
        status="failed",
        error=f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
        duration_ms=_ms(started),
    )


def _enqueue_embedding(article_id: int, log) -> None:
    try:
        embed_article.delay(article_id)
    except Exception:
        # the article just stays without an embedding (not searchable yet)
        log.exception("embed_enqueue_failed", article_id=article_id)


@celery_app.task(bind=True, max_retries=3, name="app.worker.tasks.summarize_article")
def summarize_article(self, article_id: int) -> dict:
    started = time.monotonic()
    log = logger.bind(article_id=article_id)
    cache_hit = False

    # 1) read the article, look for a ready summary of the same text
    with session_scope() as session:
        article = session.get(Article, article_id)
        if article is None or article.summary_status != SummaryStatus.PENDING:
            # already handled (a repeated delivery of the task) or deleted
            log.info(
                "summarize_article", status="not_pending", duration_ms=_ms(started)
            )
            return {"status": "not_pending"}

        text = _article_input(article.title, article.content)
        if not text:
            article.summary_status = SummaryStatus.SKIPPED.value
            log.info(
                "summarize_article",
                status="skipped",
                reason="no_text",
                duration_ms=_ms(started),
            )
            return {"status": "skipped"}

        cached = session.execute(
            select(Article.summary, Article.summary_model)
            .where(
                Article.content_hash == article.content_hash,
                Article.id != article.id,
                Article.summary_status == SummaryStatus.DONE.value,
                Article.summary.is_not(None),
            )
            .limit(1)
        ).first()
        if cached is not None:
            article.summary = cached.summary
            article.summary_model = cached.summary_model
            article.tokens_used = 0
            article.summary_status = SummaryStatus.DONE.value
            cache_hit = True

    if cache_hit:
        # after the commit: the embedding task must see the finished summary
        _enqueue_embedding(article_id, log)
        log.info(
            "summarize_article",
            status="done",
            cache_hit=True,
            tokens=0,
            duration_ms=_ms(started),
        )
        return {"status": "done", "cache_hit": True}

    summarizer = get_summarizer()  # a configuration error is raised, not swallowed
    redis_client = get_redis()

    # 2) budget check and the LLM call, no DB connection is held meanwhile
    try:
        if budget_exceeded(redis_client):
            _set_final_status(article_id, SummaryStatus.SKIPPED)
            log.warning(
                "summarize_article",
                status="skipped",
                reason="daily_token_budget",
                duration_ms=_ms(started),
            )
            return {"status": "skipped"}
        result = summarizer.summarize(text)
    except (LLMError, redis.RedisError) as exc:
        retryable = isinstance(exc, redis.RedisError) or exc.retryable
        if retryable and self.request.retries < self.max_retries:
            log.warning(
                "summarize_article",
                status="retry",
                error=f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
                attempt=self.request.retries + 1,
                duration_ms=_ms(started),
            )
            raise self.retry(
                exc=exc, countdown=retry_delay(self.request.retries)
            ) from exc
        _fail_article(article_id, exc, log, started)
        return {"status": "failed"}
    except Exception as exc:
        log.exception("summarize_article_unexpected_error")
        _fail_article(article_id, exc, log, started)
        return {"status": "failed"}

    # 3) count the tokens and save the summary
    try:
        add_tokens(redis_client, result.tokens)
    except redis.RedisError:
        # the money is already spent: do not throw the summary away (and do not
        # retry, which would pay for the same article twice)
        log.warning("token_accounting_failed", tokens=result.tokens)

    with session_scope() as session:
        article = session.get(Article, article_id)
        if article is not None and article.summary_status == SummaryStatus.PENDING:
            article.summary = result.text
            article.summary_model = summarizer.model
            article.tokens_used = result.tokens
            article.summary_status = SummaryStatus.DONE.value

    _enqueue_embedding(article_id, log)
    log.info(
        "summarize_article",
        status="done",
        cache_hit=False,
        model=summarizer.model,
        tokens=result.tokens,
        duration_ms=_ms(started),
    )
    return {"status": "done", "cache_hit": False, "tokens": result.tokens}


@celery_app.task(bind=True, max_retries=3, name="app.worker.tasks.embed_article")
def embed_article(self, article_id: int) -> dict:
    started = time.monotonic()
    log = logger.bind(article_id=article_id)

    # 1) read the finished summary
    with session_scope() as session:
        article = session.get(Article, article_id)
        if (
            article is None
            or article.summary_status != SummaryStatus.DONE
            or not article.summary
        ):
            log.info("embed_article", status="skipped", duration_ms=_ms(started))
            return {"status": "skipped"}
        text = _article_input(article.title, article.summary)

    embedder = get_embedder()  # a configuration error is raised, not swallowed

    # 2) compute the vector, no DB connection is held meanwhile
    try:
        vector = embedder.embed(text)
    except LLMError as exc:
        if exc.retryable and self.request.retries < self.max_retries:
            log.warning(
                "embed_article",
                status="retry",
                error=f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
                attempt=self.request.retries + 1,
                duration_ms=_ms(started),
            )
            raise self.retry(
                exc=exc, countdown=retry_delay(self.request.retries)
            ) from exc
        log.warning(
            "embed_article",
            status="failed",
            error=f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
            duration_ms=_ms(started),
        )
        return {"status": "failed"}
    except Exception:
        log.exception("embed_article_unexpected_error")
        return {"status": "failed"}

    # 3) save it
    with session_scope() as session:
        article = session.get(Article, article_id)
        if article is not None:
            article.embedding = vector

    log.info(
        "embed_article", status="done", model=embedder.model, duration_ms=_ms(started)
    )
    return {"status": "done"}
