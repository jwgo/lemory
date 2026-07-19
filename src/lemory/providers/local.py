"""Fully-local provider: ONNX embeddings via fastembed, no API key at all.

    [lemory]
    provider = "local"          # or just have no API key set with
                                # fastembed installed (pip install lemory[local])

Search/index run entirely on this machine (dragonkue's Korean-tuned
multilingual-e5-small-ko-v2, 384d, via a community ONNX export downloaded once
from HuggingFace). ask() needs a generator LLM, so it raises with guidance
unless a Gemini/OpenAI key is also configured — in that mixed mode, embeddings
stay local and only answer generation uses the API.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from .base import normalize_embeddings

LOCAL_EMBED_DIM = 384

# Default local embedder: dragonkue's Korean-tuned multilingual-e5-small
# (384d, ~9ms/embed). fastembed has no built-in entry for it, so we register a
# community ONNX export below. Measured dense doc@8 0.86 vs the old MiniLM's
# 0.14 on KorMapleQA Korean semantic retrieval — the reason it is the default.
DEFAULT_EMBED_MODEL = "dragonkue/multilingual-e5-small-ko-v2"
_ONNX_SOURCE = "pos090011/multilingual-e5-small-ko-v2-onnx"
# The e5-ko default rides a community ONNX export (downloaded once, then cached
# locally). If that repo is unreachable at first install, we FAIL LOUD with the
# remedy rather than silently swapping models: an auto-swap is invisible to the
# embed-signature/cache (which key off the config's model name), so it would
# cache MiniLM vectors under e5 keys and never re-embed. This bundled built-in
# (same 384d) is the manual fallback we point the user at.
_FALLBACK_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# e5-family models are trained with task prefixes; other models take raw text
_TASK_PREFIX = {"RETRIEVAL_DOCUMENT": "passage: ", "RETRIEVAL_QUERY": "query: "}

_REGISTERED: set = set()


def _register_custom(model: str) -> None:
    """Register models fastembed doesn't ship in its built-in registry (our
    Korean e5) so `TextEmbedding(model_name=...)` can load them. Idempotent."""
    if model != DEFAULT_EMBED_MODEL or model in _REGISTERED:
        return
    _REGISTERED.add(model)
    try:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        TextEmbedding.add_custom_model(
            model=model, pooling=PoolingType.MEAN, normalization=True,
            sources=ModelSource(hf=_ONNX_SOURCE), dim=LOCAL_EMBED_DIM,
            model_file="onnx/model.onnx")
    except Exception:
        pass  # already registered in this process, or fastembed too old


def _local_generate(prompt: str, system: str | None,
                    repo: str | None = None, file: str | None = None) -> str:
    """On-device answer for a keyless local install: Gemma 4 on llama.cpp (the
    same engine as the embedder) when `lemory[llama]` is installed, else a
    helpful error. Lets ask() and the console search view answer with no key.

    repo/file come from config (the model the console 'Models' card selects) so
    the search/ask path answers with the SAME model as the assistant — not a
    separate hardcoded default."""
    from . import gemma

    ok, _ = gemma.available()
    if ok:
        kw = {}
        if repo and file:
            kw = {"repo": repo, "file": file}
        return gemma.generate(system or "", prompt, **kw)
    raise RuntimeError(
        "로컬 답변 생성기가 없습니다: 검색은 오프라인으로 되지만 ask(답변)는 LLM이 "
        ' 필요합니다. 온디바이스 답변은 pip install "lemory[llama]" (Gemma 4), '
        "또는 GEMINI_API_KEY(무료)로 켜집니다."
    )


class LocalClient:
    """LLMClient implementation with local embeddings and no generator."""

    def __init__(self, embed_model: str = DEFAULT_EMBED_MODEL, generator=None,
                 answer_repo: str | None = None, answer_file: str | None = None):
        self.llm_model = generator.llm_model if generator else "none (local search-only)"
        self.embed_model = embed_model
        self.embed_dim = LOCAL_EMBED_DIM
        self._model = None
        self._lock = threading.Lock()
        self._generator = generator  # optional API client for ask()
        # configured on-device answer model (shared with the assistant), so
        # search/ask uses the model the user actually selected
        self._answer_repo = answer_repo
        self._answer_file = answer_file

    def _embedder(self):
        with self._lock:
            if self._model is None:
                import warnings

                _register_custom(self.embed_model)
                from fastembed import TextEmbedding

                with warnings.catch_warnings():
                    # fastembed >=0.6 warns that this model now uses mean
                    # pooling — informational for retrainers, alarming noise
                    # in every CLI run for users; our index and queries use
                    # the same pooling either way, so relevance is unaffected.
                    # (message-level filter: the warning's stacklevel points
                    # at our call site, so a module= filter can't catch it)
                    warnings.simplefilter("ignore", UserWarning)
                    try:
                        self._model = TextEmbedding(model_name=self.embed_model)
                    except Exception as exc:  # community ONNX repo unreachable/removed
                        if self.embed_model != DEFAULT_EMBED_MODEL:
                            raise
                        raise RuntimeError(
                            f"Could not load the default embedder "
                            f"'{DEFAULT_EMBED_MODEL}' ({exc}). It downloads once from "
                            f"a community ONNX export; if that HuggingFace repo is "
                            f"unreachable, set local_embed_model = "
                            f'"{_FALLBACK_EMBED_MODEL}" (bundled, 384d) in lemory.toml '
                            f"and run `lemory index --full`."
                        ) from exc
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
        return _local_generate(prompt, system, self._answer_repo, self._answer_file)

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any:
        if self._generator is not None:
            return self._generator.generate_json(prompt, system=system, **kw)
        from .base import parse_json_loose
        return parse_json_loose(
            _local_generate(prompt, system, self._answer_repo, self._answer_file))

    def close(self) -> None:
        if self._generator is not None:
            self._generator.close()
