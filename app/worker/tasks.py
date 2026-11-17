import logging

from sqlalchemy import select

from app.db.sync import session_scope
from app.models import Feed
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.worker.tasks.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="app.worker.tasks.fetch_all_feeds")
def fetch_all_feeds() -> int:
    with session_scope() as session:
        feed_ids = list(
            session.scalars(select(Feed.id).where(Feed.is_active.is_(True)))
        )
    logger.info("fetch_all_feeds: %d active feeds", len(feed_ids))
    return len(feed_ids)
