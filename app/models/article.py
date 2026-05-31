from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from app.db.database import Base

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, index = True)
    feed_id = Column(Integer, ForeignKey('feeds.id'), nullable=False)
    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    content = Column(Text)
    published_at = Column(DateTime)
    summary = Column(Text)

    scores = relationship('ArticleScore', back_populates='article')

class ArticleScore(Base):
    __tablename__ = 'article_scores'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    article_id = Column(Integer, ForeignKey('articles.id'), nullable=False)
    score = Column(Float, default=0.0)
    is_sent = Column(Boolean, default=False)

    article = relationship('Article', back_populates='scores')