"""Minimal, robust Gemini REST client (LLM + embeddings).

Built for the free tier: sliding-window RPM throttling, honest 429/503 retry
with server-advised delays, model fallback, and JSON-mode generation.
No SDK dependency — a single httpx client against generativelanguage.googleapis.com.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any, Optional

import httpx
import numpy as np

from .base import RateLimiter, normalize_embeddings, parse_json_loose

log = logging.getLogger("lemory.gemini")

BASE = "https://generativelanguage.googleapis.com/v1beta"


def _retry_delay_from_429(body: str) -> Optional[float]:
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    return float(m.group(1)) if m else None


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        llm_model: str = "gemini-2.5-flash",
        llm_fallback_model: str = "gemini-2.5-flash-lite",
        llm_rpm: int = 8,
        embed_model: str = "gemini-embedding-001",
        embed_dim: int = 768,
        embed_rpm: int = 90,
        embed_batch: int = 64,
        max_output_tokens: int = 2048,
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.llm_model = llm_model
        self.llm_fallback_model = llm_fallback_model
        self.embed_model = embed_model
        self.embed_dim = embed_dim
        self.embed_batch = max(1, min(embed_batch, 96))  # API limit is 100/batch
        self.max_output_tokens = max_output_tokens
        self._llm_limiter = RateLimiter(llm_rpm)
        self._embed_limiter = RateLimiter(embed_rpm)
        self._http = httpx.Client(
            timeout=timeout, headers={"x-goog-api-key": api_key, "Content-Type": "application/json"}
        )

    # ------------------------------------------------------------------ http
    def _post(
        self, url: str, payload: dict, limiter: RateLimiter,
        max_tries: int = 6, max_rate_limit_tries: int = 20,
    ) -> dict:
        """POST with retries. Rate limits (429) get their own, more patient
        budget: they are transient per-minute windows, not real failures —
        free-tier keys can sit at the TPM ceiling for several minutes."""
        last_err: Exception | None = None
        attempt = 0
        rate_limited = 0
        while attempt < max_tries and rate_limited < max_rate_limit_tries:
            limiter.acquire()
            try:
                r = self._http.post(url, json=payload)
            except httpx.HTTPError as e:  # network hiccup
                last_err = e
                attempt += 1
                time.sleep(min(2**attempt, 20) + random.random())
                continue
            if r.status_code == 200:
                return r.json()
            body = r.text[:2000]
            if r.status_code == 429:
                rate_limited += 1
                delay = _retry_delay_from_429(body) or min(15 * rate_limited, 60)
                log.warning("429 from Gemini, sleeping %.1fs", delay)
                time.sleep(delay + random.random())
                last_err = RuntimeError(f"429: {body[:200]}")
                continue
            if r.status_code in (500, 502, 503, 504):
                last_err = RuntimeError(f"{r.status_code}: {body[:200]}")
                attempt += 1
                time.sleep(min(2**attempt * 2, 30) + random.random())
                continue
            raise RuntimeError(f"Gemini error {r.status_code}: {body}")
        raise RuntimeError(f"Gemini request failed after {max_tries} tries: {last_err}")

    # ------------------------------------------------------------------- llm
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        model: str | None = None,
        thinking_budget: int = 0,
        max_output_tokens: int | None = None,
    ) -> str:
        """Single-turn text generation. Returns the model's text."""
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens or self.max_output_tokens,
                "thinkingConfig": {"thinkingBudget": thinking_budget},
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        models = [model] if model else [self.llm_model, self.llm_fallback_model]
        models = list(dict.fromkeys(models))  # dedupe, keep order
        last: Exception | None = None
        for i, m in enumerate(models):
            url = f"{BASE}/models/{m}:generateContent"
            has_fallback = i < len(models) - 1
            try:
                data = self._post(
                    url, payload, self._llm_limiter,
                    # don't camp on a saturated model when another is available
                    max_rate_limit_tries=3 if has_fallback else 20,
                )
                return _extract_text(data)
            except Exception as e:  # fall through to fallback model
                last = e
                log.warning("model %s failed (%s)", m, e)
        raise RuntimeError(f"all models failed: {last}")

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any:
        text = self.generate(prompt, system=system, json_mode=True, **kw)
        return parse_json_loose(text)

    # ------------------------------------------------------------- embeddings
    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        """Embed texts (batched). Returns L2-normalized float32 array [n, dim]."""
        out = np.zeros((len(texts), self.embed_dim), dtype=np.float32)
        B = self.embed_batch
        for i in range(0, len(texts), B):
            batch = texts[i : i + B]
            payload = {
                "requests": [
                    {
                        "model": f"models/{self.embed_model}",
                        "content": {"parts": [{"text": t[:8000]}]},
                        "taskType": task_type,
                        "outputDimensionality": self.embed_dim,
                    }
                    for t in batch
                ]
            }
            url = f"{BASE}/models/{self.embed_model}:batchEmbedContents"
            data = self._post(url, payload, self._embed_limiter)
            vecs = [e["values"] for e in data["embeddings"]]
            out[i : i + len(batch)] = np.asarray(vecs, dtype=np.float32)
        # truncated MRL dims must be re-normalized
        return normalize_embeddings(out)

    def close(self) -> None:
        self._http.close()


def _extract_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"unexpected Gemini response shape: {json.dumps(data)[:400]}") from e


