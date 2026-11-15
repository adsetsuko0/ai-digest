import pytest
from sqlalchemy import func, select

from app.models.feed import Feed, UserFeed


async def add_feed(client, headers, url="https://example.com/rss", tags=None):
    return await client.post(
        "/feeds", json={"url": url, "tags": tags or []}, headers=headers
    )


async def test_create_feed_normalizes_tags(client, alice):
    response = await add_feed(client, alice, tags=["News", " news ", "AI"])

    assert response.status_code == 201
    data = response.json()
    assert data["url"] == "https://example.com/rss"
    assert data["tags"] == ["news", "ai"]
    assert data["is_active"] is True


async def test_create_feed_normalizes_url(client, alice):
    response = await add_feed(client, alice, url="https://Example.COM/rss#top")

    assert response.status_code == 201
    assert response.json()["url"] == "https://example.com/rss"


async def test_duplicate_feed_for_same_user_returns_409(client, alice):
    assert (await add_feed(client, alice)).status_code == 201

    response = await add_feed(client, alice)

    assert response.status_code == 409
    assert response.json()["detail"] == "Feed already added"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://example.com/rss",
        "not a url",
    ],
)
async def test_unsafe_or_invalid_url_returns_422(client, alice, url):
    response = await add_feed(client, alice, url=url)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "tags",
    [[""], ["x" * 33], ["t"] * 11],
    ids=["empty tag", "tag too long", "too many tags"],
)
async def test_invalid_tags_return_422(client, alice, tags):
    response = await add_feed(client, alice, tags=tags)

    assert response.status_code == 422


async def test_list_feeds_returns_own_feeds_in_order(client, alice):
    await add_feed(client, alice, url="https://example.com/one", tags=["a"])
    await add_feed(client, alice, url="https://example.com/two")

    response = await client.get("/feeds", headers=alice)

    assert response.status_code == 200
    feeds = response.json()
    assert [f["url"] for f in feeds] == [
        "https://example.com/one",
        "https://example.com/two",
    ]
    assert feeds[0]["tags"] == ["a"]


async def test_list_feeds_pagination(client, alice):
    for i in range(3):
        await add_feed(client, alice, url=f"https://example.com/feed{i}")

    first = await client.get("/feeds?limit=1&offset=0", headers=alice)
    second = await client.get("/feeds?limit=1&offset=1", headers=alice)
    beyond = await client.get("/feeds?limit=10&offset=3", headers=alice)

    assert [f["url"] for f in first.json()] == ["https://example.com/feed0"]
    assert [f["url"] for f in second.json()] == ["https://example.com/feed1"]
    assert beyond.json() == []


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
async def test_list_feeds_rejects_bad_pagination(client, alice, query):
    response = await client.get(f"/feeds?{query}", headers=alice)

    assert response.status_code == 422


async def test_delete_feed(client, alice):
    feed_id = (await add_feed(client, alice)).json()["id"]

    response = await client.delete(f"/feeds/{feed_id}", headers=alice)

    assert response.status_code == 204
    assert (await client.get("/feeds", headers=alice)).json() == []


async def test_delete_unknown_feed_returns_404(client, alice):
    response = await client.delete("/feeds/999", headers=alice)

    assert response.status_code == 404


async def test_feeds_require_authentication(client):
    assert (await client.get("/feeds")).status_code == 401
    assert (
        await client.post("/feeds", json={"url": "https://example.com"})
    ).status_code == 401
    assert (await client.delete("/feeds/1")).status_code == 401


async def test_feed_row_is_shared_between_users(client, db_session, alice, bob):
    await add_feed(client, alice, url="https://example.com/shared")
    await add_feed(client, bob, url="https://example.com/shared")

    feeds = await db_session.scalar(select(func.count()).select_from(Feed))
    links = await db_session.scalar(select(func.count()).select_from(UserFeed))

    assert feeds == 1  # одна лента в базе...
    assert links == 2  # ...и две связи "пользователь - лента"
