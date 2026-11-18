from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    if not settings.DATABASE_SYNC_URL:
        raise RuntimeError("DATABASE_SYNC_URL is not set")
    # created on first use, not at import: the API never needs the sync engine
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit on success, roll back on any error, always close."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
