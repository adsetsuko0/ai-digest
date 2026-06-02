from sqlalchemy.ext.asyncio import create_async_engine
from app.db.base import Base
from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL)
