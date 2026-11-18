import datetime
import random
import time

import structlog
from sqlalchemy import exists, select

from app.core.config import settings
from app.db.sync import session_scope
from app.models import Feed, UserFeed
from app.services.collector import store_entries
from app.services.fetcher import FetchError, fetch_feed_content
from app.services.parser import FeedParseError, parse_feed
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
    with session_scope() as session:
        feed = session.get(Feed, feed_id)
        if feed is None:
            return {"status": "skipped"}
        new = 0 if parsed is None else store_entries(session, feed, parsed.entries)
        if parsed is not None and parsed.title:
            feed.title = parsed.title
        feed.etag = result.etag
        feed.last_modified = result.last_modified
        feed.consecutive_errors = 0
        feed.last_error = None
        feed.last_fetched_at = datetime.datetime.now(datetime.UTC)

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
