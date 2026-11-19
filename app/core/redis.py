from functools import lru_cache

import redis
import redis.asyncio as aioredis

from app.core.config import settings


@lru_cache
def get_redis() -> redis.Redis:
    """Sync Redis client for the worker (created on first use, like the sync DB engine)."""
    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


@lru_cache
def _get_async_redis() -> aioredis.Redis:
    # short timeouts: a dead Redis must not make the API hang
    return aioredis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_timeout=2,
        socket_connect_timeout=1,
    )


def get_cache() -> aioredis.Redis:
    """FastAPI dependency: the async Redis client used to cache responses."""
    return _get_async_redis()
