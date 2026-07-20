"""OpenAI provider (LLM + embeddings) with the same interface as GeminiClient.

Lemory is provider-agnostic: set `provider = "openai"` (or just have only
OPENAI_API_KEY in the environment) and everything · indexing, retrieval,
ask() · runs on OpenAI models instead of Gemini.

Note: switching embedding providers changes the vector space; run
`lemory index --full` afterwards (cached embeddings are keyed by model,
so nothing is silently mixed).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx
import numpy as np

from .base import RateLimiter, normalize_embeddings, parse_json_loose

log = logging.getLogger("lemory.openai")

BASE = "https://api.openai.com/v1"


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After may be seconds ('37') or an HTTP-date · only trust seconds."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        llm_model: str = "gpt-4o-mini",
        llm_rpm: int = 60,
        embed_model: str = "text-embedding-3-small",
        embed_dim: int = 768,
        embed_rpm: int = 300,
        max_output_tokens: int = 2048,
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.llm_model = llm_model
        self.embed_model = embed_model
        self.embed_dim = embed_dim
        self.max_output_tokens = max_output_tokens
        self._llm_limiter = RateLimiter(llm_rpm)
        self._embed_limiter = RateLimiter(embed_rpm)
        self._http = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------ http
    def _post(
        self, url: str, payload: dict, limiter,
        max_tries: int = 6, max_rate_limit_tries: int = 20,
    ) -> dict:
        """POST with retries. Like the Gemini client, 429s get their own more
        patient budget · sitting at a rate ceiling is not a real failure."""
        last_err: Exception | None = None
        attempt = 0
        rate_limited = 0
        while attempt < max_tries and rate_limited < max_rate_limit_tries:
            limiter.acquire()
            try:
                r = self._http.post(url, json=payload)
            except httpx.HTTPError as e:
                last_err = e
                attempt += 1
                time.sleep(min(2**attempt, 20) + random.random())
                continue
            if r.status_code == 200:
                return r.json()
            body = r.text[:1000]
            if r.status_code == 429:
                rate_limited += 1
                delay = _parse_retry_after(r.headers.get("retry-after")) or min(
                    15 * rate_limited, 60)
                last_err = RuntimeError(f"429: {body[:200]}")
                time.sleep(delay + random.random())
                continue
            if r.status_code >= 500:
                attempt += 1
                last_err = RuntimeError(f"{r.status_code}: {body[:200]}")
                time.sleep(min(2**attempt * 2, 30) + random.random())
                continue
            raise RuntimeError(f"OpenAI error {r.status_code}: {body}")
        raise RuntimeError(f"OpenAI request failed after {max_tries} tries: {last_err}")

    # ------------------------------------------------------------------- llm
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        model: str | None = None,
        thinking_budget: int = 0,  # accepted for interface parity; unused
        max_output_tokens: int | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model or self.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens or self.max_output_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post(f"{BASE}/chat/completions", payload, self._llm_limiter)
        return data["choices"][0]["message"]["content"] or ""

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any:
        text = self.generate(prompt, system=system, json_mode=True, **kw)
        return parse_json_loose(text)

    # ------------------------------------------------------------- embeddings
    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        out = np.zeros((len(texts), self.embed_dim), dtype=np.float32)
        B = 256
        for i in range(0, len(texts), B):
            batch = [t[:8000] if t.strip() else " " for t in texts[i : i + B]]
            data = self._post(
                f"{BASE}/embeddings",
                {"model": self.embed_model, "input": batch, "dimensions": self.embed_dim},
                self._embed_limiter,
            )
            for j, item in enumerate(data["data"]):
                out[i + j] = np.asarray(item["embedding"], dtype=np.float32)
        return normalize_embeddings(out)

    def close(self) -> None:
        self._http.close()
