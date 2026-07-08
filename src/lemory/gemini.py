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
import threading
import time
from collections import deque
from typing import Any, Optional

import httpx
import numpy as np

log = logging.getLogger("lemory.gemini")

BASE = "https://generativelanguage.googleapis.com/v1beta"


class RateLimiter:
    """Sliding-window requests-per-minute limiter (thread-safe)."""

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] > 60.0:
                    self._stamps.popleft()
                if len(self._stamps) < self.rpm:
                    self._stamps.append(now)
                    return
                wait = 60.0 - (now - self._stamps[0]) + 0.05
            time.sleep(min(wait, 5.0))


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
        max_output_tokens: int = 2048,
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.llm_model = llm_model
        self.llm_fallback_model = llm_fallback_model
        self.embed_model = embed_model
        self.embed_dim = embed_dim
        self.max_output_tokens = max_output_tokens
        self._llm_limiter = RateLimiter(llm_rpm)
        self._embed_limiter = RateLimiter(embed_rpm)
        self._http = httpx.Client(
            timeout=timeout, headers={"x-goog-api-key": api_key, "Content-Type": "application/json"}
        )

    # ------------------------------------------------------------------ http
    def _post(self, url: str, payload: dict, limiter: RateLimiter, max_tries: int = 6) -> dict:
        last_err: Exception | None = None
        for attempt in range(max_tries):
            limiter.acquire()
            try:
                r = self._http.post(url, json=payload)
            except httpx.HTTPError as e:  # network hiccup
                last_err = e
                time.sleep(min(2**attempt, 20) + random.random())
                continue
            if r.status_code == 200:
                return r.json()
            body = r.text[:2000]
            if r.status_code == 429:
                delay = _retry_delay_from_429(body) or min(15 * (attempt + 1), 60)
                log.warning("429 from Gemini, sleeping %.1fs", delay)
                time.sleep(delay + random.random())
                last_err = RuntimeError(f"429: {body[:200]}")
                continue
            if r.status_code in (500, 502, 503, 504):
                last_err = RuntimeError(f"{r.status_code}: {body[:200]}")
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
        last: Exception | None = None
        for m in models:
            url = f"{BASE}/models/{m}:generateContent"
            try:
                data = self._post(url, payload, self._llm_limiter)
                return _extract_text(data)
            except Exception as e:  # fall through to fallback model
                last = e
                log.warning("model %s failed (%s)", m, e)
        raise RuntimeError(f"all models failed: {last}")

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any:
        text = self.generate(prompt, system=system, json_mode=True, **kw)
        return _parse_json_loose(text)

    # ------------------------------------------------------------- embeddings
    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        """Embed texts (batched). Returns L2-normalized float32 array [n, dim]."""
        out = np.zeros((len(texts), self.embed_dim), dtype=np.float32)
        B = 96  # API limit is 100 per batch
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
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text], task_type="RETRIEVAL_QUERY")[0]

    def close(self) -> None:
        self._http.close()


def _extract_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"unexpected Gemini response shape: {json.dumps(data)[:400]}") from e


def _parse_json_loose(text: str) -> Any:
    """Parse JSON, tolerating markdown fences and stray prose."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # last resort: grab the outermost JSON object/array
        m = re.search(r"[\[{].*[\]}]", t, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise
