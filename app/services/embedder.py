import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import settings
from app.services.summarizer import (
    RETRYABLE_STATUSES,
    TIMEOUT,
    LLMPermanentError,
    LLMUpstreamError,
)

MAX_INPUT_CHARS = 8000
WORD = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    model: str
    dim: int

    def embed(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Deterministic vectors for tests and demos, no network.

    Every word is hashed to a position of the vector, so texts that share words
    get close vectors. It is lexical, not semantic: "car" and "automobile" are
    unrelated for it.
    """

    model = "fake"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for word in WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:  # no words at all: a fixed unit vector keeps the maths valid
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


class OpenAICompatibleEmbedder:
    """Calls POST {base_url}/embeddings of any OpenAI-compatible API.

    No retries here, the Celery task retries. EMBEDDING_DIM must match the model.
    """

    def __init__(self, base_url: str, api_key: str, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self._url = base_url.rstrip("/") + "/embeddings"
        self._api_key = api_key

    def embed(self, text: str) -> list[float]:
        text = text.strip()
        if not text:
            raise LLMPermanentError("Text is empty")
        payload = {"model": self.model, "input": text[:MAX_INPUT_CHARS]}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            # no redirects (httpx default): they would carry the API key elsewhere
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(self._url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMUpstreamError(f"Request failed: {type(exc).__name__}") from exc

        status = response.status_code
        if status >= 500 or status in RETRYABLE_STATUSES:
            raise LLMUpstreamError(f"HTTP {status}")
        if not 200 <= status < 300:
            raise LLMPermanentError(
                f"HTTP {status}"
            )  # never the body: it may echo the key
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> list[float]:
        try:
            vector = response.json()["data"][0]["embedding"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMPermanentError("Unexpected response format") from exc
        valid = isinstance(vector, list) and all(
            isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)
            for x in vector
        )
        if not valid:
            raise LLMPermanentError("Unexpected response format")
        if len(vector) != self.dim:
            raise LLMPermanentError(
                f"Embedding has {len(vector)} dimensions, but EMBEDDING_DIM is {self.dim}"
            )
        return [float(x) for x in vector]


@lru_cache
def get_embedder() -> Embedder:
    if settings.EMBEDDING_PROVIDER == "fake":
        return FakeEmbedder(settings.EMBEDDING_DIM)
    api_key = settings.LLM_API_KEY.get_secret_value()
    required = {
        "LLM_BASE_URL": settings.LLM_BASE_URL,
        "LLM_API_KEY": api_key,
        "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"EMBEDDING_PROVIDER=openai requires: {', '.join(missing)}")
    return OpenAICompatibleEmbedder(
        settings.LLM_BASE_URL, api_key, settings.EMBEDDING_MODEL, settings.EMBEDDING_DIM
    )
