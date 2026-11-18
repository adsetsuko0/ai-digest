from functools import lru_cache

import redis

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
