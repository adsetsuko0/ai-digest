import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db import sync
from app.db.base import Base
from app.models import Feed


@pytest.fixture
def sqlite_url(monkeypatch):
    sync.get_session_factory.cache_clear()
    monkeypatch.setattr(settings, "DATABASE_SYNC_URL", "sqlite://")
    yield
    sync.get_session_factory().kw["bind"].dispose()
    sync.get_session_factory.cache_clear()


def test_session_scope_commits_and_rolls_back(sqlite_url):
    Base.metadata.create_all(sync.get_session_factory().kw["bind"])
    with sync.session_scope() as session:
        session.add(Feed(url="https://a.example.com/rss"))
    with pytest.raises(RuntimeError):
        with sync.session_scope() as session:
            session.add(Feed(url="https://b.example.com/rss"))
            session.flush()
            raise RuntimeError("boom")
    with sync.session_scope() as session:
        urls = list(session.scalars(select(Feed.url)))
    assert urls == ["https://a.example.com/rss"]


def test_missing_sync_url_gives_clear_error(monkeypatch):
    sync.get_session_factory.cache_clear()
    monkeypatch.setattr(settings, "DATABASE_SYNC_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_SYNC_URL"):
        sync.get_session_factory()
