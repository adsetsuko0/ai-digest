from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.worker.tasks as tasks
from app.db import sync
from app.db.base import Base
from app.models import Feed
from app.worker.celery_app import celery_app


def test_ping_task():
    assert tasks.ping() == "pong"


def test_celery_is_configured_for_safe_retries():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.beat_schedule["fetch-all-feeds"]["schedule"] == 1800


def test_fetch_all_feeds_counts_only_active_feeds(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                Feed(url="https://a.example.com/rss", is_active=True),
                Feed(url="https://b.example.com/rss", is_active=False),
            ]
        )
        session.commit()
    monkeypatch.setattr(sync, "get_session_factory", lambda: factory)

    assert tasks.fetch_all_feeds() == 1
