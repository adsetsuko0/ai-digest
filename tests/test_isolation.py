"""Главное свойство сервиса: данные одного пользователя недоступны другому."""

from sqlalchemy import func, select

from app.db.database import get_db
from app.main import app
from app.models.feed import Feed, UserFeed
from tests.conftest import TestSessionLocal


async def test_user_cannot_see_feeds_of_another_user(client, alice, bob):
    await client.post(
        "/feeds",
        json={"url": "https://example.com/alice-only", "tags": ["secret"]},
        headers=alice,
    )

    alice_feeds = (await client.get("/feeds", headers=alice)).json()
    bob_feeds = (await client.get("/feeds", headers=bob)).json()

    assert len(alice_feeds) == 1
    assert bob_feeds == []


async def test_user_cannot_delete_feed_of_another_user(client, alice, bob):
    feed_id = (
        await client.post(
            "/feeds", json={"url": "https://example.com/a"}, headers=alice
        )
    ).json()["id"]

    response = await client.delete(f"/feeds/{feed_id}", headers=bob)

    assert response.status_code == 404  # для Боба такой ленты "не существует"
    assert len((await client.get("/feeds", headers=alice)).json()) == 1


async def test_same_url_can_be_added_by_two_users_with_own_tags(client, alice, bob):
    url = "https://example.com/shared"
    first = await client.post(
        "/feeds", json={"url": url, "tags": ["work"]}, headers=alice
    )
    second = await client.post(
        "/feeds", json={"url": url, "tags": ["fun"]}, headers=bob
    )

    assert first.status_code == 201
    assert (
        second.status_code == 201
    )  # не 409: дубль считается только внутри одного пользователя
    assert (await client.get("/feeds", headers=alice)).json()[0]["tags"] == ["work"]
    assert (await client.get("/feeds", headers=bob)).json()[0]["tags"] == ["fun"]


async def test_deleting_shared_feed_removes_only_own_link(client, alice, bob):
    url = "https://example.com/shared"
    await client.post("/feeds", json={"url": url}, headers=alice)
    bob_feed_id = (await client.post("/feeds", json={"url": url}, headers=bob)).json()[
        "id"
    ]

    await client.delete(f"/feeds/{bob_feed_id}", headers=bob)

    assert (await client.get("/feeds", headers=bob)).json() == []
    assert len((await client.get("/feeds", headers=alice)).json()) == 1


async def test_each_user_sees_only_own_profile(client, alice, bob):
    alice_me = (await client.get("/users/me", headers=alice)).json()
    bob_me = (await client.get("/users/me", headers=bob)).json()

    assert alice_me["email"] == "alice@example.com"
    assert bob_me["email"] == "bob@example.com"


async def test_settings_change_affects_only_current_user(client, alice, bob):
    await client.patch(
        "/users/me/settings", json={"timezone": "Europe/Warsaw"}, headers=alice
    )

    assert (await client.get("/users/me", headers=alice)).json()[
        "timezone"
    ] == "Europe/Warsaw"
    assert (await client.get("/users/me", headers=bob)).json()["timezone"] == "UTC"


async def test_lost_race_on_feed_creation_is_handled(client, db_session, alice):
    """Два пользователя одновременно добавляют новый URL: один создаёт ленту первым.

    Второй запрос сначала не видит ленту (проверка прошла до чужого коммита), потом
    упирается в уникальный URL и должен спокойно подключиться к уже созданной ленте.
    Гонку воспроизводим искусственно: лента уже есть в базе, но первый поиск её "не находит".
    """
    db_session.add(Feed(url="https://example.com/race"))
    await db_session.commit()

    class RacySession:
        def __init__(self, session):
            self._session = session
            self._first_lookup = True

        async def execute(self, *args, **kwargs):
            if self._first_lookup:
                self._first_lookup = False

                class NotFound:
                    def scalar_one_or_none(self):
                        return None

                return NotFound()
            return await self._session.execute(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._session, name)

    async def racy_db():
        async with TestSessionLocal() as session:
            yield RacySession(session)

    app.dependency_overrides[get_db] = racy_db

    response = await client.post(
        "/feeds", json={"url": "https://example.com/race"}, headers=alice
    )

    assert response.status_code == 201
    assert await db_session.scalar(select(func.count()).select_from(Feed)) == 1
    assert await db_session.scalar(select(func.count()).select_from(UserFeed)) == 1
