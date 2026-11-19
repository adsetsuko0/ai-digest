import datetime

import pytest

from app.core.config import settings
from app.models import Article
from app.services.embedder import FakeEmbedder
from tests.conftest import register_and_login
from tests.test_digest import walk

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder(settings.EMBEDDING_DIM)
NOW = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=datetime.UTC)


def at(minutes: int) -> datetime.datetime:
    return NOW + datetime.timedelta(minutes=minutes)


def distance(a, b) -> float:
    return 1 - sum(x * y for x, y in zip(a, b, strict=True))


async def subscribe(client, headers, url, tags=None) -> int:
    response = await client.post(
        "/feeds", json={"url": url, "tags": tags or []}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def add_article(
    factory, feed_id, n, *, title, summary, status="done", embed=True
):
    article = Article(
        feed_id=feed_id,
        url=f"https://example.com/a{n}",
        title=title,
        content="text",
        content_hash=f"hash{n}",
        published_at=at(n),
        summary=summary if status == "done" else None,
        summary_status=status,
        summary_model="fake",
        tokens_used=5,
        embedding=EMBEDDER.embed(f"{title}\n\n{summary}") if embed else None,
    )
    async with factory() as session:
        session.add(article)
        await session.commit()
        return article.id


TEXTS = {
    1: ("Python asyncio tutorial", "How to use asyncio in python programs"),
    2: ("Cooking pasta", "A simple pasta recipe with tomatoes"),
    3: ("Python web framework", "A fast python framework for the web"),
}


async def test_search_ranks_only_own_articles_by_similarity(pg_client, pg_factory):
    alice = await register_and_login(pg_client, "alice@example.com")
    bob = await register_and_login(pg_client, "bob@example.com")
    alice_feed = await subscribe(pg_client, alice, "https://example.com/rss")
    bob_feed = await subscribe(pg_client, bob, "https://example.org/rss")
    ids = {
        n: await add_article(pg_factory, alice_feed, n, title=t, summary=s)
        for n, (t, s) in TEXTS.items()
    }
    # the best possible match, but it belongs to bob
    bob_id = await add_article(
        pg_factory, bob_feed, 9, title=TEXTS[1][0], summary=TEXTS[1][1]
    )

    query = "python asyncio"
    response = await pg_client.get("/search", params={"q": query}, headers=alice)

    assert response.status_code == 200, response.text
    results = response.json()["items"]
    q = EMBEDDER.embed(query)
    expected = sorted(
        ids, key=lambda n: distance(q, EMBEDDER.embed("\n\n".join(TEXTS[n])))
    )
    assert [r["id"] for r in results] == [ids[n] for n in expected]
    assert bob_id not in [r["id"] for r in results]
    assert results[0]["score"] >= results[-1]["score"]


async def test_search_skips_articles_without_embedding_or_summary(
    pg_client, pg_factory
):
    alice = await register_and_login(pg_client, "alice@example.com")
    feed = await subscribe(pg_client, alice, "https://example.com/rss")
    good = await add_article(pg_factory, feed, 1, title="Python", summary="python text")
    await add_article(
        pg_factory, feed, 2, title="Python", summary="python", embed=False
    )
    await add_article(
        pg_factory, feed, 3, title="Python", summary="python", status="pending"
    )

    response = await pg_client.get("/search", params={"q": "python"}, headers=alice)

    assert [r["id"] for r in response.json()["items"]] == [good]


async def test_search_respects_the_limit(pg_client, pg_factory):
    alice = await register_and_login(pg_client, "alice@example.com")
    feed = await subscribe(pg_client, alice, "https://example.com/rss")
    for n in range(1, 5):
        await add_article(pg_factory, feed, n, title=f"Python {n}", summary="python")

    response = await pg_client.get(
        "/search", params={"q": "python", "limit": 2}, headers=alice
    )

    assert len(response.json()["items"]) == 2


async def test_digest_pagination_and_tag_filter_work_on_postgres(pg_client, pg_factory):
    alice = await register_and_login(pg_client, "alice@example.com")
    news = await subscribe(pg_client, alice, "https://example.com/rss", tags=["news"])
    tech = await subscribe(pg_client, alice, "https://example.org/rss", tags=["tech"])
    article_dates = {}

    news_ids = []
    for n in (1, 3, 5):
        article_id = await add_article(pg_factory, news, n, title=f"N{n}", summary="s")
        news_ids.append(article_id)
        article_dates[article_id] = at(n)

    tech_ids = []
    for n in (2, 4):
        article_id = await add_article(pg_factory, tech, n, title=f"T{n}", summary="s")
        tech_ids.append(article_id)
        article_dates[article_id] = at(n)

    seen, pages = await walk(pg_client, alice, limit=2)
    assert seen == sorted(
        news_ids + tech_ids,
        key=lambda article_id: article_dates[article_id],
        reverse=True,
    )
    assert pages == 3

    response = await pg_client.get("/digest", params={"tag": "news"}, headers=alice)
    assert [i["id"] for i in response.json()["items"]] == sorted(news_ids, reverse=True)
