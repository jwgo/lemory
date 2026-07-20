"""Provider-neutral pieces: the client protocol, rate limiting, JSON parsing.

Every provider client (Gemini, OpenAI, future ones) implements LLMClient.
The Engine talks only to this interface; adding a provider means one new
module here plus one entry in the factory · nothing else changes.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from typing import Any, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class LLMClient(Protocol):
    llm_model: str
    embed_model: str
    embed_dim: int

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        model: str | None = None,
        thinking_budget: int = 0,
        max_output_tokens: int | None = None,
    ) -> str: ...

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any: ...

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray: ...

    def close(self) -> None: ...


class RateLimiter:
    """Requests-per-minute limiter (thread-safe).

    Enforces both a sliding 60s window AND even spacing between requests
    (after a small burst allowance) · burst-then-wait patterns trip
    fixed-window server quotas even when the average rate is compliant."""

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self.min_interval = 60.0 / self.rpm
        self.burst = max(2, self.rpm // 4)  # small bursts OK, then paced
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._stamps and now - self._stamps[0] > 60.0:
                    self._stamps.popleft()
                spaced_ok = (
                    len(self._stamps) < self.burst
                    or (now - self._stamps[-1]) >= self.min_interval
                )
                if len(self._stamps) < self.rpm and spaced_ok:
                    self._stamps.append(now)
                    return
                if not spaced_ok:
                    wait = self.min_interval - (now - self._stamps[-1]) + 0.01
                else:
                    wait = 60.0 - (now - self._stamps[0]) + 0.05
            time.sleep(min(max(wait, 0.01), 5.0))


def parse_json_loose(text: str) -> Any:
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


def normalize_embeddings(out: np.ndarray) -> np.ndarray:
    """L2-normalize rows in place-safe fashion (zero rows stay zero)."""
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return out / norms
