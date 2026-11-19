import pytest

from app.services.summarizer import LLMUpstreamError


async def test_search_requires_authentication(client):
    assert (await client.get("/search", params={"q": "python"})).status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "x" * 201},
        {"q": "ok", "limit": 0},
        {"q": "ok", "limit": 51},
    ],
)
async def test_search_rejects_bad_parameters(client, alice, params):
    response = await client.get("/search", params=params, headers=alice)

    assert response.status_code == 422


async def test_search_answers_503_when_the_embedding_service_fails(
    client, alice, monkeypatch
):
    class Broken:
        def embed(self, text):
            raise LLMUpstreamError("HTTP 503")

    monkeypatch.setattr("app.api.search.get_embedder", lambda: Broken())

    response = await client.get("/search", params={"q": "python"}, headers=alice)

    assert response.status_code == 503
    assert response.json()["detail"] == "Search is temporarily unavailable"
