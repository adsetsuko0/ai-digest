import math

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.core.config import settings
from app.services.embedder import (
    FakeEmbedder,
    OpenAICompatibleEmbedder,
    get_embedder,
)
from app.services.summarizer import LLMPermanentError, LLMUpstreamError

BASE_URL = "https://llm.example.com/v1"
URL = f"{BASE_URL}/embeddings"


def similarity(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.fixture(autouse=True)
def clear_factory_cache():
    get_embedder.cache_clear()
    yield
    get_embedder.cache_clear()


@pytest.fixture
def embedder():
    return OpenAICompatibleEmbedder(BASE_URL, "sk-test", "test-embed", dim=3)


def embedding_response(vector):
    return httpx.Response(200, json={"data": [{"embedding": vector}]})


# --- FakeEmbedder -----------------------------------------------------------------


def test_fake_has_the_requested_size_and_unit_length():
    vector = FakeEmbedder(64).embed("some words in a text")
    assert len(vector) == 64
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


def test_fake_is_deterministic():
    fake = FakeEmbedder(64)
    assert fake.embed("Same text") == fake.embed("same TEXT")


def test_fake_texts_with_shared_words_are_closer():
    fake = FakeEmbedder(1024)
    base = fake.embed("python asyncio tutorial")
    close = fake.embed("python asyncio guide")
    far = fake.embed("cooking pasta recipe")

    assert similarity(base, base) > 0.999
    assert similarity(base, close) > 0.5
    assert similarity(base, far) < 0.5


def test_fake_text_without_words_still_gives_a_valid_vector():
    vector = FakeEmbedder(8).embed("!!! ???")
    assert math.isclose(sum(v * v for v in vector), 1.0)


# --- factory ----------------------------------------------------------------------


def test_factory_returns_fake_by_default(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "fake")
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 16)
    result = get_embedder()
    assert isinstance(result, FakeEmbedder)
    assert result.dim == 16


def test_factory_openai_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "")
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr(""))
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "")
    with pytest.raises(
        RuntimeError, match="LLM_BASE_URL.*LLM_API_KEY.*EMBEDDING_MODEL"
    ):
        get_embedder()


def test_factory_builds_openai_embedder(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_BASE_URL", BASE_URL)
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr("sk-test"))
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "test-embed")
    result = get_embedder()
    assert isinstance(result, OpenAICompatibleEmbedder)
    assert result.model == "test-embed"


# --- OpenAICompatibleEmbedder -----------------------------------------------------


def test_openai_success_returns_the_vector(embedder):
    with respx.mock() as router:
        route = router.post(URL).mock(return_value=embedding_response([1, 0.5, -2]))
        assert embedder.embed("some text") == [1.0, 0.5, -2.0]

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert b"some text" in request.content


def test_openai_wrong_dimension_is_a_permanent_error(embedder):
    with respx.mock() as router:
        router.post(URL).mock(return_value=embedding_response([0.1, 0.2]))
        with pytest.raises(LLMPermanentError, match="EMBEDDING_DIM"):
            embedder.embed("text")


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_openai_temporary_http_errors_are_retryable(embedder, status):
    with respx.mock() as router:
        router.post(URL).mock(return_value=httpx.Response(status))
        with pytest.raises(LLMUpstreamError) as info:
            embedder.embed("text")
    assert info.value.retryable is True


@pytest.mark.parametrize("status", [400, 401, 404])
def test_openai_client_errors_are_permanent(embedder, status):
    with respx.mock() as router:
        router.post(URL).mock(return_value=httpx.Response(status))
        with pytest.raises(LLMPermanentError):
            embedder.embed("text")


def test_openai_timeout_is_retryable(embedder):
    with respx.mock() as router:
        router.post(URL).mock(side_effect=httpx.ConnectTimeout("too slow"))
        with pytest.raises(LLMUpstreamError):
            embedder.embed("text")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json={"data": [{"embedding": "abc"}]}),
        httpx.Response(200, json={"data": [{"embedding": [1, "x", 3]}]}),
        httpx.Response(200, json={"data": [{"embedding": [1, True, 3]}]}),
    ],
    ids=["not-json", "empty-object", "no-data", "not-a-list", "text-item", "bool-item"],
)
def test_openai_garbage_response_is_a_permanent_error(embedder, response):
    with respx.mock() as router:
        router.post(URL).mock(return_value=response)
        with pytest.raises(LLMPermanentError):
            embedder.embed("text")


def test_openai_empty_text_is_rejected_without_calling_the_api(embedder):
    with respx.mock(assert_all_called=False) as router:
        route = router.post(URL).mock(return_value=embedding_response([1, 2, 3]))
        with pytest.raises(LLMPermanentError):
            embedder.embed("   ")
    assert route.called is False


def test_error_message_does_not_leak_the_api_key(embedder):
    response = httpx.Response(401, json={"error": "invalid key sk-test"})
    with respx.mock() as router:
        router.post(URL).mock(return_value=response)
        with pytest.raises(LLMPermanentError) as info:
            embedder.embed("text")
    assert "sk-test" not in str(info.value)
