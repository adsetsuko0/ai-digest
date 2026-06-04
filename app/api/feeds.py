from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.db.database import get_db
from app.models.feed import Feed, UserFeed
from app.models.user import User
from app.schemas.feed import FeedCreate, FeedResponse
from app.core.dependencies import get_current_user


router = APIRouter(prefix='/feeds', tags=['feeds'])

@router.post('', response_model=FeedResponse, status_code=201)
async def create_feed(
    data: FeedCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(Feed).where(Feed.url == data.url))
    feed = result.scalar_one_or_none()

    if not feed:
        feed = Feed(url=data.url)
        db.add(feed)
        await db.flush()

    result = await db.execute(
        select(UserFeed).where(
            UserFeed.user_id == current_user.id,
            UserFeed.feed_id == feed.id
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feed already added"
        )
    
    user_feed = UserFeed(user_id=current_user.id, feed_id=feed.id, tags=data.tags)

    db.add(user_feed)
    await db.commit()
    await db.refresh(feed)

    feed_response = FeedResponse(
        id=feed.id,
        url=feed.url,
        title=feed.title,
        is_active=feed.is_active,
        tags=data.tags
    )
    return feed_response

@router.get('', response_model=List[FeedResponse])
async def get_feeds(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Feed, UserFeed).join(
            UserFeed, UserFeed.feed_id == Feed.id
        ).where(UserFeed.user_id == current_user.id)
    )
    rows = result.all()

    return [
        FeedResponse(
            id=feed.id,
            url=feed.url,
            title=feed.title,
            is_active=feed.is_active,
            tags=user_feed.tags or []
        ) for feed, user_feed in rows
    ]

@router.delete('/{feed_id}', status_code=204)
async def delete_feed(
    feed_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(UserFeed).where(
            UserFeed.user_id == current_user.id,
            UserFeed.feed_id == feed_id
        )
    )
    user_feed = result.scalar_one_or_none()

    if not user_feed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found")

    await db.delete(user_feed)
    await db.commit()