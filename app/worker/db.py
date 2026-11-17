from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)
