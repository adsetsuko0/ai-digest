import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id"), index=True)
    url: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str | None] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    summary: Mapped[str | None] = mapped_column(Text)
