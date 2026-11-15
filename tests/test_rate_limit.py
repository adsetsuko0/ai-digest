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
