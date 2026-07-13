"""Fully-local provider: ONNX embeddings via fastembed, no API key at all.

    [lemory]
    provider = "local"          # or just have no API key set with
                                # fastembed installed (pip install lemory[local])

Search/index run entirely on this machine (paraphrase-multilingual-MiniLM-L12-v2,
384d, KR/EN capable; ~220MB downloaded once from HuggingFace). ask() needs a
generator LLM, so it raises with guidance unless a Gemini/OpenAI key is also
configured — in that mixed mode, embeddings stay local and only answer
generation uses the API.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from .base import normalize_embeddings

LOCAL_EMBED_DIM = 384

# e5-family models are trained with task prefixes; other models take raw text
_TASK_PREFIX = {"RETRIEVAL_DOCUMENT": "passage: ", "RETRIEVAL_QUERY": "query: "}


def _local_generate(prompt: str, system: str | None) -> str:
    """On-device answer for a keyless local install: LiteRT-LM (Gemma 4 E2B)
    when `lemory[assistant]` is installed, else a helpful error. Lets ask()
    and the console search view answer with no API key and no Ollama."""
    from . import litert

    ok, _ = litert.available()
    if ok:
        return litert.generate(system or "", prompt)
    raise RuntimeError(
        "로컬 답변 생성기가 없습니다: 검색은 오프라인으로 되지만 ask(답변)는 LLM이 "
        ' 필요합니다. 온디바이스 답변은 pip install "lemory[assistant]" (Gemma 4 E2B), '
        "또는 GEMINI_API_KEY(무료)로 켜집니다."
    )


class LocalClient:
    """LLMClient implementation with local embeddings and no generator."""

    def __init__(self, embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                 generator=None):
        self.llm_model = generator.llm_model if generator else "none (local search-only)"
        self.embed_model = embed_model
        self.embed_dim = LOCAL_EMBED_DIM
        self._model = None
        self._lock = threading.Lock()
        self._generator = generator  # optional API client for ask()

    def _embedder(self):
        with self._lock:
            if self._model is None:
                import warnings

                from fastembed import TextEmbedding

                with warnings.catch_warnings():
                    # fastembed >=0.6 warns that this model now uses mean
                    # pooling — informational for retrainers, alarming noise
                    # in every CLI run for users; our index and queries use
                    # the same pooling either way, so relevance is unaffected.
                    # (message-level filter: the warning's stacklevel points
                    # at our call site, so a module= filter can't catch it)
                    warnings.simplefilter("ignore", UserWarning)
                    self._model = TextEmbedding(model_name=self.embed_model)
            return self._model

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        prefix = _TASK_PREFIX.get(task_type, "passage: ") if "e5" in self.embed_model.lower() else ""
        vecs = list(self._embedder().embed([prefix + t[:4000] for t in texts]))
        out = np.asarray(vecs, dtype=np.float32)
        return normalize_embeddings(out)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text], task_type="RETRIEVAL_QUERY")[0]

    # ------------------------------------------------------------- generation
    def generate(self, prompt: str, system: str | None = None, **kw) -> str:
        if self._generator is not None:
            return self._generator.generate(prompt, system=system, **kw)
        return _local_generate(prompt, system)

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any:
        if self._generator is not None:
            return self._generator.generate_json(prompt, system=system, **kw)
        from .base import parse_json_loose
        return parse_json_loose(_local_generate(prompt, system))

    def close(self) -> None:
        if self._generator is not None:
            self._generator.close()
