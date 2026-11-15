from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.database import get_db
from app.models.feed import Feed, UserFeed
from app.models.user import User
from app.schemas.feed import FeedCreate, FeedResponse

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.post("", response_model=FeedResponse, status_code=201)
async def create_feed(
    data: FeedCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.id  # read it before any rollback expires the object

    result = await db.execute(select(Feed).where(Feed.url == data.url))
    feed = result.scalar_one_or_none()
    if feed is None:
        feed = Feed(url=data.url)
        db.add(feed)
        try:
            await db.flush()
        except IntegrityError:  # another request created it first
            await db.rollback()
            result = await db.execute(select(Feed).where(Feed.url == data.url))
            feed = result.scalar_one()

    db.add(UserFeed(user_id=user_id, feed_id=feed.id, tags=data.tags))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Feed already added"
        ) from None
    await db.refresh(feed)
    return FeedResponse(
        id=feed.id,
        url=feed.url,
        title=feed.title,
        is_active=feed.is_active,
        tags=data.tags,
    )


@router.get("", response_model=list[FeedResponse])
async def get_feeds(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Feed, UserFeed)
        .join(UserFeed, UserFeed.feed_id == Feed.id)
        .where(UserFeed.user_id == current_user.id)
        .order_by(UserFeed.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        FeedResponse(
            id=feed.id,
            url=feed.url,
            title=feed.title,
            is_active=feed.is_active,
            tags=user_feed.tags or [],
        )
        for feed, user_feed in result.all()
    ]


@router.delete("/{feed_id}", status_code=204)
async def delete_feed(
    feed_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserFeed).where(
            UserFeed.user_id == current_user.id, UserFeed.feed_id == feed_id
        )
    )
    user_feed = result.scalar_one_or_none()

    if not user_feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
        )

    await db.delete(user_feed)
    await db.commit()
