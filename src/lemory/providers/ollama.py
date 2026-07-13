"""Fully-local provider via Ollama: LLM + embeddings on your own machine.

    [lemory]
    provider = "ollama"
    # defaults, override if you like:
    # ollama_llm_model = "gemma3n:e4b"            # Gemma 3n E4B, 4-bit quant (~5.6GB)
    # ollama_embed_model = "hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0"  # (~640MB, 1024d)
    # ollama_host = "http://127.0.0.1:11434"

Everything — indexing, search, AND ask() answer generation — runs offline.
`lemory setup` can configure this mode interactively and tells you which
`ollama pull` commands to run.

Minimum specs (see docs/GUIDE.ko.md): 8 GB RAM for the default pair
(comfortable: 16 GB); CPU-only works, a GPU makes generation pleasant.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import numpy as np

from .base import normalize_embeddings, parse_json_loose

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_LLM = "gemma3n:e4b"
DEFAULT_EMBED = "hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0"
DEFAULT_EMBED_DIM = 1024


def _friendly(e: Exception, host: str) -> RuntimeError:
    return RuntimeError(
        f"Ollama unreachable at {host} — is it running? "
        f"Install: https://ollama.com  ·  start: `ollama serve`  ·  "
        f"models: `ollama pull {DEFAULT_LLM}` + `ollama pull {DEFAULT_EMBED}` "
        f"({e.__class__.__name__}: {e})"
    )


class OllamaClient:
    """LLMClient implementation backed by a local Ollama server."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        llm_model: str = DEFAULT_LLM,
        embed_model: str = DEFAULT_EMBED,
        embed_dim: int = DEFAULT_EMBED_DIM,
        reranker_model: str = "",
        max_output_tokens: int = 2048,
        timeout: float = 300.0,  # local CPU generation can be slow; don't give up
    ):
        self.host = host.rstrip("/")
        self.llm_model = llm_model
        self.embed_model = embed_model
        self.embed_dim = embed_dim
        self.reranker_model = reranker_model
        self.max_output_tokens = max_output_tokens
        self._http = httpx.Client(timeout=timeout)

    # ---------------------------------------------------------------- server
    def server_alive(self) -> bool:
        try:
            return self._http.get(f"{self.host}/api/version").status_code == 200
        except httpx.HTTPError:
            return False

    def installed_models(self) -> list[str]:
        try:
            r = self._http.get(f"{self.host}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError:
            return []

    # ------------------------------------------------------------ embeddings
    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        out = np.zeros((len(texts), self.embed_dim), dtype=np.float32)
        B = 32  # keep request bodies sane for long chunks
        for i in range(0, len(texts), B):
            batch = [t[:6000] for t in texts[i : i + B]]
            try:
                r = self._http.post(
                    f"{self.host}/api/embed",
                    json={"model": self.embed_model, "input": batch},
                )
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise _friendly(e, self.host) from e
            vecs = r.json().get("embeddings", [])
            if len(vecs) != len(batch):
                raise RuntimeError(
                    f"ollama /api/embed returned {len(vecs)} vectors for {len(batch)} inputs "
                    f"(model {self.embed_model!r} pulled? `ollama pull {self.embed_model}`)"
                )
            arr = np.asarray(vecs, dtype=np.float32)
            if arr.shape[1] != self.embed_dim:
                raise RuntimeError(
                    f"embedding dim mismatch: model {self.embed_model!r} returned "
                    f"{arr.shape[1]}d, config says {self.embed_dim}d — set "
                    f"ollama_embed_dim = {arr.shape[1]} in lemory.toml"
                )
            out[i : i + len(batch)] = arr
        return normalize_embeddings(out)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text], task_type="RETRIEVAL_QUERY")[0]

    # ------------------------------------------------------------ generation
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        **_: Any,  # accept and ignore API-provider-specific kwargs (model=, thinking_budget=...)
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": self.llm_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_output_tokens or self.max_output_tokens,
            },
        }
        if json_mode:
            body["format"] = "json"
        try:
            r = self._http.post(f"{self.host}/api/chat", json=body)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise _friendly(e, self.host) from e
        data = r.json()
        content = (data.get("message") or {}).get("content", "")
        if not content and data.get("error"):
            raise RuntimeError(f"ollama error: {data['error']}")
        return content

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any:
        text = self.generate(prompt, system=system, json_mode=True, **kw)
        return parse_json_loose(text)

    # ------------------------------------------------------------- reranking
    def rerank_scores(self, query: str, docs: list[str]) -> list[float]:
        """Dedicated cross-encoder reranking with a Qwen3-Reranker-style model.

        Unlike generic LLM 0-10 self-scoring (noisy on small models), a
        purpose-built reranker judges query-document relevance directly. We
        read its yes/no verdict per document (1.0 relevant, 0.0 not); the
        caller keeps fusion order as the within-group tiebreaker. One model
        call per document, so this is a slow, opt-in quality mode."""
        model = self.reranker_model or self.llm_model
        scores: list[float] = []
        for doc in docs:
            prompt = (
                "Judge whether the Document is relevant to the Query. "
                "Answer only 'yes' or 'no'.\n"
                f"<Query>: {query}\n<Document>: {doc[:1200]}"
            )
            try:
                r = self._http.post(f"{self.host}/api/generate", json={
                    "model": model, "prompt": prompt, "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 4},
                })
                r.raise_for_status()
                text = r.json().get("response", "").lower()
            except httpx.HTTPError:
                text = ""
            # thinking models emit '<think>\nYes' etc; a bare 'no' must not be
            # matched by the 'no' inside a longer token, so check word-ish
            scores.append(1.0 if ("yes" in text and "no" not in text.split()) else
                          (1.0 if text.strip().endswith("yes") else 0.0))
        return scores

    def close(self) -> None:
        self._http.close()
