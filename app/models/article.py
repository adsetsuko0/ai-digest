import datetime
import enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SummaryStatus(enum.StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        CheckConstraint(
            "summary_status IN ('pending', 'done', 'failed', 'skipped')",
            name="ck_articles_summary_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id"), index=True)
    url: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str | None] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    summary: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    summary_status: Mapped[str] = mapped_column(
        String(16),
        default=SummaryStatus.PENDING.value,
        server_default=SummaryStatus.PENDING.value,
    )
    summary_model: Mapped[str | None] = mapped_column(String(100))
    tokens_used: Mapped[int | None] = mapped_column()
