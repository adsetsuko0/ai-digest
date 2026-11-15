from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Feed(Base):
    __tablename__ = "feeds"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    last_fetched_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)

    user_feeds = relationship("UserFeed", back_populates="feed")


class UserFeed(Base):
    __tablename__ = "user_feeds"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", name="uq_user_feed"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    feed_id = Column(Integer, ForeignKey("feeds.id"), nullable=False, index=True)
    tags = Column(JSON, default=list)

    feed = relationship("Feed", back_populates="user_feeds")
