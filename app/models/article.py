import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    scores: Mapped[list["ArticleScore"]] = relationship(back_populates="article")


class ArticleScore(Base):
    __tablename__ = "article_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uq_user_article"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    score: Mapped[float | None] = mapped_column(Float, default=0.0)
    is_sent: Mapped[bool | None] = mapped_column(Boolean, default=False)

    article: Mapped["Article"] = relationship(back_populates="scores")
