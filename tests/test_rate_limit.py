import pytest

from app.core.rate_limit import limiter


@pytest.fixture
def rate_limit_on():
    """Лимиты в тестах выключены, для этого файла включаем и потом сбрасываем."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


async def test_login_is_limited_to_10_per_minute(client, rate_limit_on):
    body = {"email": "x@example.com", "password": "whatever-password"}

    statuses = [
        (await client.post("/auth/login", json=body)).status_code for _ in range(11)
    ]

    assert statuses[:10] == [401] * 10  # проверка пароля выполняется, но он неверный
    assert statuses[10] == 429


async def test_register_is_limited_to_10_per_hour(client, rate_limit_on):
    statuses = []
    for i in range(11):
        response = await client.post(
            "/auth/register",
            json={"email": f"user{i}@example.com", "password": "testpassword123"},
        )
        statuses.append(response.status_code)

    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


async def test_digest_is_limited_to_60_per_minute(client, alice, rate_limit_on):
    statuses = [
        (await client.get("/digest", headers=alice)).status_code for _ in range(61)
    ]

    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429


async def test_search_is_limited_to_30_per_minute(
    client, alice, rate_limit_on, monkeypatch
):
    async def no_results(*args, **kwargs):
        return []

    # the vector query only works on PostgreSQL, the limit does not care
    monkeypatch.setattr("app.api.search.search_articles", no_results)

    statuses = [
        (await client.get("/search", params={"q": "python"}, headers=alice)).status_code
        for _ in range(31)
    ]

    assert statuses[:30] == [200] * 30
    assert statuses[30] == 429
