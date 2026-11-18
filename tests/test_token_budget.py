import datetime

import fakeredis
import pytest

from app.core.config import settings
from app.core.redis import get_redis
from app.services.token_budget import (
    add_tokens,
    budget_exceeded,
    daily_key,
    tokens_used_today,
)


@pytest.fixture
def client():
    return fakeredis.FakeRedis(decode_responses=True)


def test_counter_starts_at_zero(client):
    assert tokens_used_today(client) == 0


def test_tokens_accumulate(client):
    assert add_tokens(client, 100) == 100
    assert add_tokens(client, 50) == 150
    assert tokens_used_today(client) == 150


def test_counter_expires_by_itself(client):
    add_tokens(client, 10)
    assert 0 < client.ttl(daily_key()) <= 2 * 24 * 3600


def test_each_day_has_its_own_key():
    today = datetime.date(2026, 11, 18)
    assert daily_key(today) == "llm:tokens:2026-11-18"
    assert daily_key(today) != daily_key(today + datetime.timedelta(days=1))


def test_budget_is_exceeded_when_reached(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_BUDGET", 100)
    add_tokens(client, 99)
    assert budget_exceeded(client) is False
    add_tokens(client, 1)
    assert budget_exceeded(client) is True


def test_zero_budget_blocks_everything(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_BUDGET", 0)
    assert budget_exceeded(client) is True


def test_redis_client_is_created_lazily_and_cached(monkeypatch):
    get_redis.cache_clear()
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    client = get_redis()
    assert client is get_redis()
    assert client.connection_pool.connection_kwargs["host"] == "localhost"
    client.close()
    get_redis.cache_clear()
