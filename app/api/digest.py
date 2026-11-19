import datetime
import hashlib
import json

import redis
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.core.redis import get_cache
from app.db.database import get_db
from app.models.user import User
from app.schemas.digest import DigestPage
from app.services.digest import InvalidCursor, as_utc, decode_cursor, get_digest_page

router = APIRouter(tags=["digest"])
logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 60


def cache_key(
    user_id: int,
    tag: str | None,
    feed_id: int | None,
    since: datetime.datetime | None,
    limit: int,
    cursor: str | None,
) -> str:
    params = json.dumps(
        {
            "tag": tag,
            "feed_id": feed_id,
            "since": since.isoformat() if since else None,
            "limit": limit,
            "cursor": cursor,
        },
        sort_keys=True,
    )
    # the user id is part of the key, so one user can never get another's page
    return f"digest:{user_id}:{hashlib.sha256(params.encode()).hexdigest()[:32]}"


@router.get("/digest", response_model=DigestPage)
@limiter.limit("60/minute")
async def get_digest(
    request: Request,
    tag: str | None = Query(None, min_length=1, max_length=32),
    feed_id: int | None = Query(None, ge=1),
    since: datetime.datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    cache: aioredis.Redis = Depends(get_cache),
):
    user_id = current_user.id
    if tag is not None:
        tag = tag.strip().lower()  # tags are stored in this form
        if not tag:
            raise HTTPException(status_code=422, detail="Tag must not be blank")

    if since is not None:
        try:
            since = as_utc(since)
        except OverflowError:
            raise HTTPException(
                status_code=422, detail="since is out of range"
            ) from None

    after = None
    if cursor is not None:
        try:
            after = decode_cursor(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="Invalid cursor") from None

    key = cache_key(user_id, tag, feed_id, since, limit, cursor)
    cache_ok = True
    try:
        cached = await cache.get(key)
    except redis.RedisError:
        # the cache is an optimization: without Redis we just read the database
        cache_ok = False
        cached = None
        logger.warning("digest_cache_unavailable")
    if cached is not None:
        return Response(content=cached, media_type="application/json")

    page = await get_digest_page(
        db,
        user_id=user_id,
        tag=tag,
        feed_id=feed_id,
        since=since,
        limit=limit,
        after=after,
    )
    payload = page.model_dump_json()
    if cache_ok:
        try:
            await cache.set(key, payload, ex=CACHE_TTL_SECONDS)
        except redis.RedisError:
            logger.warning("digest_cache_unavailable")
    return Response(content=payload, media_type="application/json")
