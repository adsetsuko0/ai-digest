import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.core.config import settings
from app.services.summarizer import (
    FakeSummarizer,
    LLMPermanentError,
    LLMUpstreamError,
    OpenAICompatibleSummarizer,
    SummaryResult,
    estimate_tokens,
    get_summarizer,
)

BASE_URL = "https://llm.example.com/v1"
URL = f"{BASE_URL}/chat/completions"


@pytest.fixture(autouse=True)
def clear_factory_cache():
    get_summarizer.cache_clear()
    yield
    get_summarizer.cache_clear()


@pytest.fixture
def summarizer():
    return OpenAICompatibleSummarizer(BASE_URL, "sk-test", "test-model")


def chat_response(content="Short summary.", total_tokens=42):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"total_tokens": total_tokens},
        },
    )


# --- FakeSummarizer ---------------------------------------------------------


def test_fake_returns_first_two_sentences():
    result = FakeSummarizer().summarize("One. Two! Three? Four.")
    assert result.text == "One. Two!"


def test_fake_keeps_short_text_and_is_deterministic():
    fake = FakeSummarizer()
    assert fake.summarize("Only one sentence.").text == "Only one sentence."
    text = "A. B. C."
    assert fake.summarize(text) == fake.summarize(text)


def test_fake_reports_model_and_token_estimate():
    text = "x" * 400
    result = FakeSummarizer().summarize(text)
    assert FakeSummarizer.model == "fake"
    assert result.tokens == estimate_tokens(text) == 100


# --- factory ----------------------------------------------------------------


def test_factory_returns_fake_by_default(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "fake")
    assert isinstance(get_summarizer(), FakeSummarizer)


def test_factory_result_is_cached(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "fake")
    assert get_summarizer() is get_summarizer()


def test_factory_openai_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "")
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr(""))
    monkeypatch.setattr(settings, "LLM_MODEL", "")
    with pytest.raises(RuntimeError, match="LLM_BASE_URL.*LLM_API_KEY.*LLM_MODEL"):
        get_summarizer()


def test_factory_builds_openai_summarizer(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_BASE_URL", BASE_URL)
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr("sk-test"))
    monkeypatch.setattr(settings, "LLM_MODEL", "test-model")
    result = get_summarizer()
    assert isinstance(result, OpenAICompatibleSummarizer)
    assert result.model == "test-model"


# --- OpenAICompatibleSummarizer ---------------------------------------------


def test_openai_success_returns_text_and_tokens(summarizer):
    with respx.mock() as router:
        route = router.post(URL).mock(return_value=chat_response())
        result = summarizer.summarize("Article text")

    assert result == SummaryResult("Short summary.", 42)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert "Article text" in body["messages"][-1]["content"]


def test_openai_strips_whitespace_around_the_summary(summarizer):
    with respx.mock() as router:
        router.post(URL).mock(return_value=chat_response("  hello \n"))
        assert summarizer.summarize("text").text == "hello"


def test_openai_estimates_tokens_when_usage_is_missing(summarizer):
    response = httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    with respx.mock() as router:
        router.post(URL).mock(return_value=response)
        assert summarizer.summarize("some text").tokens > 0


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_openai_temporary_http_errors_are_retryable(summarizer, status):
    with respx.mock() as router:
        router.post(URL).mock(return_value=httpx.Response(status))
        with pytest.raises(LLMUpstreamError) as info:
            summarizer.summarize("text")
    assert info.value.retryable is True


@pytest.mark.parametrize("status", [400, 401, 404])
def test_openai_client_errors_are_permanent(summarizer, status):
    with respx.mock() as router:
        router.post(URL).mock(return_value=httpx.Response(status))
        with pytest.raises(LLMPermanentError) as info:
            summarizer.summarize("text")
    assert info.value.retryable is False


def test_openai_timeout_is_retryable(summarizer):
    with respx.mock() as router:
        router.post(URL).mock(side_effect=httpx.ConnectTimeout("too slow"))
        with pytest.raises(LLMUpstreamError):
            summarizer.summarize("text")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
    ],
    ids=["not-json", "empty-object", "no-choices", "null-content"],
)
def test_openai_garbage_response_is_permanent_error(summarizer, response):
    with respx.mock() as router:
        router.post(URL).mock(return_value=response)
        with pytest.raises(LLMPermanentError):
            summarizer.summarize("text")


def test_error_message_does_not_leak_the_api_key(summarizer):
    response = httpx.Response(401, json={"error": "invalid key sk-test"})
    with respx.mock() as router:
        router.post(URL).mock(return_value=response)
        with pytest.raises(LLMPermanentError) as info:
            summarizer.summarize("text")
    assert "sk-test" not in str(info.value)


def test_redirects_are_not_followed_so_the_key_stays_home(summarizer):
    redirect = httpx.Response(302, headers={"Location": "https://evil.example.com/x"})
    with respx.mock(assert_all_called=False) as router:
        router.post(URL).mock(return_value=redirect)
        evil = router.post("https://evil.example.com/x").mock(
            return_value=chat_response()
        )
        with pytest.raises(LLMPermanentError):
            summarizer.summarize("text")
    assert evil.called is False
