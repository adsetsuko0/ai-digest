from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, Feed, UserFeed
from app.models.article import SummaryStatus
from app.schemas.digest import DigestFeed
from app.schemas.search import SearchItem


async def search_articles(
    db: AsyncSession, *, user_id: int, vector: list[float], limit: int
) -> list[SearchItem]:
    """Articles from the user's own feeds, closest to the query vector first."""
    distance = Article.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(
            Article.id,
            Article.title,
            Article.url,
            Article.summary,
            func.coalesce(Article.published_at, Article.fetched_at).label("sort_at"),
            Feed.id.label("feed_id"),
            Feed.title.label("feed_title"),
            UserFeed.tags.label("tags"),
            distance,
        )
        .select_from(Article)
        .join(Feed, Feed.id == Article.feed_id)
        .join(UserFeed, UserFeed.feed_id == Feed.id)
        .where(
            UserFeed.user_id == user_id,  # the isolation between users
            Article.summary_status == SummaryStatus.DONE.value,
            Article.summary.is_not(None),
            Article.embedding.is_not(None),
        )
        .order_by(distance, Article.id)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        SearchItem(
            id=row.id,
            title=row.title,
            url=row.url,
            summary=row.summary,
            feed=DigestFeed(id=row.feed_id, title=row.feed_title),
            published_at=row.sort_at,
            tags=row.tags or [],
            score=round(1.0 - float(row.distance), 4),
        )
        for row in rows
    ]
