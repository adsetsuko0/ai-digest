from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    feed_id = Column(Integer, ForeignKey("feeds.id"), nullable=False, index=True)
    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    content = Column(Text)
    published_at = Column(DateTime(timezone=True))
    summary = Column(Text)

    scores = relationship("ArticleScore", back_populates="article")


class ArticleScore(Base):
    __tablename__ = "article_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uq_user_article"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    score = Column(Float, default=0.0)
    is_sent = Column(Boolean, default=False)

    article = relationship("Article", back_populates="scores")
