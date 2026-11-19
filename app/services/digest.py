import base64
import datetime
import json

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, Feed, UserFeed
from app.models.article import SummaryStatus
from app.schemas.digest import DigestFeed, DigestItem, DigestPage

# Many feeds give no publication date, so the order is by "date, or the time we
# collected the article". NULL dates would break keyset pagination.
SORT_AT = func.coalesce(Article.published_at, Article.fetched_at)


class InvalidCursor(ValueError):
    """The cursor is not one we produced."""


def as_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)  # SQLite returns naive UTC
    return value.astimezone(datetime.UTC)


def encode_cursor(sort_at: datetime.datetime, article_id: int) -> str:
    raw = json.dumps([as_utc(sort_at).isoformat(), article_id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime.datetime, int]:
    try:
        sort_at, article_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if isinstance(article_id, bool) or not isinstance(article_id, int):
            raise ValueError("article id must be an integer")
        return as_utc(datetime.datetime.fromisoformat(sort_at)), article_id
    except (ValueError, TypeError, OverflowError) as exc:
        raise InvalidCursor("Invalid cursor") from exc


async def get_digest_page(
    db: AsyncSession,
    *,
    user_id: int,
    tag: str | None = None,
    feed_id: int | None = None,
    since: datetime.datetime | None = None,
    limit: int = 20,
    after: tuple[datetime.datetime, int] | None = None,
) -> DigestPage:
    """One page of summaries of the articles from the user's own feeds, newest first."""
    stmt = (
        # only the columns we return: the article text can be 20 000 characters
        select(
            Article.id,
            Article.title,
            Article.url,
            Article.summary,
            SORT_AT.label("sort_at"),
            Feed.id.label("feed_id"),
            Feed.title.label("feed_title"),
            UserFeed.tags.label("tags"),
        )
        .select_from(Article)
        .join(Feed, Feed.id == Article.feed_id)
        .join(UserFeed, UserFeed.feed_id == Feed.id)
        .where(
            UserFeed.user_id == user_id,  # the isolation between users
            Article.summary_status == SummaryStatus.DONE.value,
            Article.summary.is_not(None),
        )
        .order_by(SORT_AT.desc(), Article.id.desc())
        .limit(limit + 1)  # one extra row tells us whether there is a next page
    )
    if feed_id is not None:
        stmt = stmt.where(Feed.id == feed_id)
    if tag:
        # tags are a JSON array; looking for the quoted word works in SQLite and
        # Postgres alike (autoescape makes % and _ ordinary characters)
        stmt = stmt.where(
            cast(UserFeed.tags, String).contains(f'"{tag}"', autoescape=True)
        )
    if since is not None:
        stmt = stmt.where(SORT_AT >= as_utc(since))
    if after is not None:
        after_at, after_id = after
        # keyset: "older than the last item we gave, ties broken by id"
        stmt = stmt.where(
            or_(
                SORT_AT < after_at,
                and_(SORT_AT == after_at, Article.id < after_id),
            )
        )

    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        DigestItem(
            id=row.id,
            title=row.title,
            url=row.url,
            summary=row.summary,
            feed=DigestFeed(id=row.feed_id, title=row.feed_title),
            published_at=row.sort_at,
            tags=row.tags or [],
        )
        for row in rows
    ]
    next_cursor = encode_cursor(rows[-1].sort_at, rows[-1].id) if has_more else None
    return DigestPage(items=items, next_cursor=next_cursor)
