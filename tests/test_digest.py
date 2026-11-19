import datetime

import pytest
import redis

from app.core.redis import get_cache
from app.main import app
from app.models import Article

NOW = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=datetime.UTC)


def at(minutes: int) -> datetime.datetime:
    return NOW + datetime.timedelta(minutes=minutes)


async def subscribe(client, headers, url="https://example.com/rss", tags=None) -> int:
    response = await client.post(
        "/feeds", json={"url": url, "tags": tags or []}, headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


async def add_article(
    db_session, feed_id, n, *, status="done", published=None, fetched=None
) -> int:
    article = Article(
        feed_id=feed_id,
        url=f"https://example.com/a{n}",
        title=f"Title {n}",
        content="text",
        content_hash=f"hash{n}",
        published_at=published,
        fetched_at=fetched or at(0),
        summary=f"Summary {n}" if status == "done" else None,
        summary_status=status,
        summary_model="fake",
        tokens_used=5,
    )
    db_session.add(article)
    await db_session.commit()
    return article.id


async def digest_ids(client, headers, **params) -> list[int]:
    response = await client.get("/digest", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


async def walk(client, headers, limit) -> tuple[list[int], int]:
    """Follow next_cursor to the end; returns all ids and the number of pages."""
    seen, pages, cursor = [], 0, None
    while True:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = (await client.get("/digest", params=params, headers=headers)).json()
        seen += [item["id"] for item in data["items"]]
        pages += 1
        cursor = data["next_cursor"]
        if cursor is None:
            return seen, pages
        assert pages < 20, "pagination does not end"


# --- basics ---------------------------------------------------------------------


async def test_digest_requires_authentication(client):
    assert (await client.get("/digest")).status_code == 401


async def test_empty_digest(client, alice):
    response = await client.get("/digest", headers=alice)

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_only_finished_summaries_are_shown(client, alice, db_session):
    feed_id = await subscribe(client, alice, tags=["news"])
    done_id = await add_article(db_session, feed_id, 1, published=at(1))
    for n, status in enumerate(["pending", "failed", "skipped"], start=2):
        await add_article(db_session, feed_id, n, status=status, published=at(n))

    items = (await client.get("/digest", headers=alice)).json()["items"]

    assert [item["id"] for item in items] == [done_id]
    item = items[0]
    assert item["title"] == "Title 1"
    assert item["url"] == "https://example.com/a1"
    assert item["summary"] == "Summary 1"
    assert item["feed"] == {"id": feed_id, "title": None}
    assert item["tags"] == ["news"]
    assert "published_at" in item
    assert "content" not in item


async def test_newest_first_and_missing_date_falls_back_to_collection_time(
    client, alice, db_session
):
    feed_id = await subscribe(client, alice)
    old = await add_article(db_session, feed_id, 1, published=at(10))
    undated = await add_article(db_session, feed_id, 2, published=None, fetched=at(20))
    new = await add_article(db_session, feed_id, 3, published=at(30))

    assert await digest_ids(client, alice) == [new, undated, old]


# --- isolation ------------------------------------------------------------------


async def test_user_sees_only_articles_of_own_feeds(client, alice, bob, db_session):
    alice_feed = await subscribe(client, alice, url="https://example.com/rss")
    bob_feed = await subscribe(client, bob, url="https://example.org/rss")
    a = await add_article(db_session, alice_feed, 1, published=at(1))
    b = await add_article(db_session, bob_feed, 2, published=at(2))

    assert await digest_ids(client, alice) == [a]
    assert await digest_ids(client, bob) == [b]


async def test_shared_feed_shows_each_users_own_tags(client, alice, bob, db_session):
    feed_id = await subscribe(client, alice, tags=["news"])
    assert await subscribe(client, bob, tags=["work"]) == feed_id
    await add_article(db_session, feed_id, 1, published=at(1))

    alice_item = (await client.get("/digest", headers=alice)).json()["items"][0]
    bob_item = (await client.get("/digest", headers=bob)).json()["items"][0]

    assert alice_item["tags"] == ["news"]
    assert bob_item["tags"] == ["work"]


async def test_unsubscribed_feed_disappears_from_the_digest(client, alice, db_session):
    feed_id = await subscribe(client, alice)
    await add_article(db_session, feed_id, 1, published=at(1))
    assert (await client.delete(f"/feeds/{feed_id}", headers=alice)).status_code == 204

    assert await digest_ids(client, alice) == []


# --- filters --------------------------------------------------------------------


async def test_filter_by_feed(client, alice, bob, db_session):
    f1 = await subscribe(client, alice, url="https://example.com/rss")
    f2 = await subscribe(client, alice, url="https://example.org/rss")
    foreign = await subscribe(client, bob, url="https://example.net/rss")
    a1 = await add_article(db_session, f1, 1, published=at(1))
    a2 = await add_article(db_session, f2, 2, published=at(2))
    await add_article(db_session, foreign, 3, published=at(3))

    assert await digest_ids(client, alice, feed_id=f1) == [a1]
    assert await digest_ids(client, alice, feed_id=f2) == [a2]
    assert await digest_ids(client, alice, feed_id=foreign) == []  # not her feed


async def test_filter_by_tag(client, alice, db_session):
    f1 = await subscribe(client, alice, url="https://example.com/rss", tags=["news"])
    f2 = await subscribe(
        client, alice, url="https://example.org/rss", tags=["tech", "ai"]
    )
    a1 = await add_article(db_session, f1, 1, published=at(1))
    a2 = await add_article(db_session, f2, 2, published=at(2))

    assert await digest_ids(client, alice, tag="news") == [a1]
    assert await digest_ids(client, alice, tag=" NEWS ") == [a1]  # same form as stored
    assert await digest_ids(client, alice, tag="ai") == [a2]
    assert await digest_ids(client, alice, tag="missing") == []
    assert (
        await digest_ids(client, alice, tag="ne") == []
    )  # part of a word is not a tag
    assert await digest_ids(client, alice, tag="%") == []  # not a wildcard


async def test_filter_since(client, alice, db_session):
    feed_id = await subscribe(client, alice)
    await add_article(db_session, feed_id, 1, published=at(5))
    a10 = await add_article(db_session, feed_id, 2, published=at(10))
    a15 = await add_article(db_session, feed_id, 3, published=at(15))

    assert await digest_ids(client, alice, since=at(10).isoformat()) == [a15, a10]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"feed_id": 0},
        {"tag": ""},
        {"tag": " "},
        {"since": "yesterday"},
    ],
)
async def test_bad_parameters_return_422(client, alice, params):
    assert (
        await client.get("/digest", params=params, headers=alice)
    ).status_code == 422


# --- pagination -----------------------------------------------------------------


async def test_pagination_visits_every_article_once(client, alice, db_session):
    feed_id = await subscribe(client, alice)
    ids = [
        await add_article(db_session, feed_id, n, published=at(n)) for n in range(1, 6)
    ]

    seen, pages = await walk(client, alice, limit=2)

    assert seen == list(reversed(ids))
    assert pages == 3


async def test_last_page_has_no_cursor(client, alice, db_session):
    feed_id = await subscribe(client, alice)
    await add_article(db_session, feed_id, 1, published=at(1))

    data = (await client.get("/digest", params={"limit": 1}, headers=alice)).json()

    assert len(data["items"]) == 1
    assert data["next_cursor"] is None  # exactly one page, nothing more


async def test_identical_dates_do_not_lose_articles_between_pages(
    client, alice, db_session
):
    feed_id = await subscribe(client, alice)
    ids = [
        await add_article(db_session, feed_id, n, published=at(1)) for n in range(1, 4)
    ]

    seen, pages = await walk(client, alice, limit=1)

    assert seen == sorted(ids, reverse=True)
    assert pages == 3


@pytest.mark.parametrize("cursor", ["garbage", "e30=", "WzFd", "W10="])
async def test_bad_cursor_returns_400(client, alice, cursor):
    response = await client.get("/digest", params={"cursor": cursor}, headers=alice)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid cursor"


# --- cache ----------------------------------------------------------------------


async def test_response_is_cached_per_user_for_a_minute(
    client, alice, bob, cache, db_session
):
    feed_id = await subscribe(client, alice)
    first_id = await add_article(db_session, feed_id, 1, published=at(1))
    first = await client.get("/digest", headers=alice)
    assert [i["id"] for i in first.json()["items"]] == [first_id]

    # a new article is in the database, but the cached answer is still served
    await add_article(db_session, feed_id, 2, published=at(2))
    second = await client.get("/digest", headers=alice)
    assert second.json() == first.json()

    user_id = (await client.get("/users/me", headers=alice)).json()["id"]
    keys = await cache.keys("digest:*")
    assert len(keys) == 1
    assert keys[0].startswith(f"digest:{user_id}:")
    assert 0 < await cache.ttl(keys[0]) <= 60

    # another user does not get alice's cached page
    assert (await client.get("/digest", headers=bob)).json()["items"] == []


class BrokenCache:
    async def get(self, *args, **kwargs):
        raise redis.ConnectionError("down")

    async def set(self, *args, **kwargs):
        raise redis.ConnectionError("down")


async def test_digest_works_when_redis_is_down(client, alice, db_session):
    app.dependency_overrides[get_cache] = lambda: BrokenCache()
    feed_id = await subscribe(client, alice)
    article_id = await add_article(db_session, feed_id, 1, published=at(1))

    assert await digest_ids(client, alice) == [article_id]
