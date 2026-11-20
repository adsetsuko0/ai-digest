import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Feed(Base):
    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    url: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str | None] = mapped_column(String)
    last_fetched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user_feeds: Mapped[list["UserFeed"]] = relationship(back_populates="feed")
    etag: Mapped[str | None] = mapped_column(String)
    last_modified: Mapped[str | None] = mapped_column(String)
    consecutive_errors: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)


class UserFeed(Base):
    __tablename__ = "user_feeds"
    __table_args__ = (UniqueConstraint("user_id", "feed_id", name="uq_user_feed"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id"), index=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, default=list)

    feed: Mapped["Feed"] = relationship(back_populates="user_feeds")
