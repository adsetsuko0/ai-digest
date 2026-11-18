import datetime

import redis

from app.core.config import settings

KEY_TTL_SECONDS = 2 * 24 * 3600  # keep a day's counter for 2 days, then Redis drops it


def daily_key(day: datetime.date | None = None) -> str:
    day = day or datetime.datetime.now(datetime.UTC).date()
    return f"llm:tokens:{day.isoformat()}"


def tokens_used_today(client: redis.Redis) -> int:
    return int(client.get(daily_key()) or 0)


def add_tokens(client: redis.Redis, tokens: int) -> int:
    """Add spent tokens to today's counter, return the new total."""
    key = daily_key()
    pipe = client.pipeline()
    pipe.incrby(key, tokens)
    pipe.expire(key, KEY_TTL_SECONDS)
    total, _ = pipe.execute()
    return int(total)


def budget_exceeded(client: redis.Redis) -> bool:
    """True when today's spending reached the budget (a budget of 0 blocks everything)."""
    return tokens_used_today(client) >= settings.LLM_DAILY_TOKEN_BUDGET
