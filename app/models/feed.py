from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base
import datetime

class Feed(Base):
    __tablename__ = "feeds"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    last_fetched_at = Column(DateTime)
    is_active = Column(Boolean, default=True)

    user_feeds = relationship("UserFeed", back_populates="feed")


class UserFeed(Base):
    __tablename__ = "user_feeds"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    feed_id = Column(Integer, ForeignKey("feeds.id"), nullable=False)
    tags = Column(JSON, default=list)

    feed = relationship("Feed", back_populates="user_feeds")