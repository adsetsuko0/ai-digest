import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import settings

TIMEOUT = httpx.Timeout(30.0, connect=5.0)  # below the Celery soft limit of 60 s
MAX_OUTPUT_TOKENS = 300
FAKE_SENTENCES = 2
RETRYABLE_STATUSES = {408, 425, 429}
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class LLMError(Exception):
    """Base class for summarizer errors."""

    retryable = False


class LLMUpstreamError(LLMError):
    """Temporary problem: 5xx, 429, timeout, network error."""

    retryable = True


class LLMPermanentError(LLMError):
    """Retrying will not help: bad key, bad request, unreadable response."""


@dataclass(frozen=True)
class SummaryResult:
    text: str
    tokens: int


class Summarizer(Protocol):
    model: str

    def summarize(self, text: str) -> SummaryResult: ...


def estimate_tokens(text: str) -> int:
    """Rough estimate (about 4 characters per token), used when the API gives no usage."""
    return max(1, len(text) // 4)


def build_messages(text: str) -> list[dict[str, str]]:
    # Temporary prompt, replaced by a prompt-injection-aware one on day 2.
    return [
        {"role": "system", "content": "Summarize the text in 2-3 sentences."},
        {"role": "user", "content": text},
    ]


class FakeSummarizer:
    """Deterministic summary (the first sentences), no network. For tests and demos."""

    model = "fake"

    def summarize(self, text: str) -> SummaryResult:
        sentences = [s for s in SENTENCE_END.split(text.strip()) if s]
        summary = " ".join(sentences[:FAKE_SENTENCES])
        return SummaryResult(text=summary, tokens=estimate_tokens(text))


class OpenAICompatibleSummarizer:
    """Calls POST {base_url}/chat/completions of any OpenAI-compatible API.

    No retries here on purpose: the Celery task retries with a growing delay,
    and retrying in both places would multiply the attempts.
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key

    def summarize(self, text: str) -> SummaryResult:
        payload = {
            "model": self.model,
            "messages": build_messages(text),
            "temperature": 0.2,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            # httpx does not follow redirects by default; that is what we want,
            # because a redirect would send the API key to another host
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(self._url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMUpstreamError(f"Request failed: {type(exc).__name__}") from exc

        status = response.status_code
        if status >= 500 or status in RETRYABLE_STATUSES:
            raise LLMUpstreamError(f"HTTP {status}")
        if not 200 <= status < 300:
            # only the status, never the body: it may echo the request or the key
            raise LLMPermanentError(f"HTTP {status}")
        return self._parse(response, text)

    @staticmethod
    def _parse(response: httpx.Response, source_text: str) -> SummaryResult:
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMPermanentError("Unexpected response format") from exc
        if not isinstance(content, str):
            raise LLMPermanentError("Unexpected response format")
        summary = content.strip()

        usage = data.get("usage") if isinstance(data, dict) else None
        tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        if not isinstance(tokens, int) or tokens < 0:
            tokens = estimate_tokens(source_text + summary)
        return SummaryResult(text=summary, tokens=tokens)


@lru_cache
def get_summarizer() -> Summarizer:
    if settings.LLM_PROVIDER == "fake":
        return FakeSummarizer()
    api_key = settings.LLM_API_KEY.get_secret_value()
    required = {
        "LLM_BASE_URL": settings.LLM_BASE_URL,
        "LLM_API_KEY": api_key,
        "LLM_MODEL": settings.LLM_MODEL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"LLM_PROVIDER=openai requires: {', '.join(missing)}")
    return OpenAICompatibleSummarizer(
        settings.LLM_BASE_URL, api_key, settings.LLM_MODEL
    )
