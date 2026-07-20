"""In-process local embeddings via llama.cpp (no daemon), the same runtime
qmd uses (node-llama-cpp) ported to Python (llama-cpp-python).

    [lemory]
    provider = "local"
    local_embed_backend = "llamacpp"   # or "auto": used when llama-cpp-python
                                        # is installed (pip install lemory[llama])

Runs **Harrier-OSS-0.6B** (Qwen3-based multilingual, Q8 GGUF) fully in this
process on Apple GPU Metal or CPU · no daemon, no server. Measured on
KorMapleQA: hybrid doc@8 0.853, the top local tier above the lighter fastembed
e5-small-ko-v2 default. The GGUF (~640MB) auto-downloads from HuggingFace once.

ask() still needs a generator LLM: pass one, or set a Gemini/OpenAI key for a
mixed mode where embeddings stay local and only answer generation uses the API.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from .base import normalize_embeddings

# Harrier-OSS-0.6B, community Q8_0 GGUF (mradermacher). 1024-dim, last-token
# pooling handled inside llama.cpp from the GGUF metadata.
DEFAULT_GGUF_REPO = "mradermacher/harrier-oss-v1-0.6b-GGUF"
DEFAULT_GGUF_FILE = "harrier-oss-v1-0.6b.Q8_0.gguf"
DEFAULT_GGUF_DIM = 1024


class LlamaCppLocalClient:
    """LLMClient with in-process llama.cpp embeddings and no external daemon."""

    def __init__(self, gguf_repo: str = DEFAULT_GGUF_REPO,
                 gguf_file: str = DEFAULT_GGUF_FILE,
                 embed_dim: int = DEFAULT_GGUF_DIM,
                 n_ctx: int = 1024, generator=None,
                 answer_repo: str | None = None, answer_file: str | None = None,
                 answer_n_ctx: int | None = None, answer_gpu_layers: int | None = None):
        self.llm_model = generator.llm_model if generator else "none (local search-only)"
        # a stable, human-readable id the index stores to detect model switches
        self.embed_model = f"llamacpp:{gguf_repo}/{gguf_file}"
        self.embed_dim = embed_dim
        self.gguf_repo = gguf_repo
        self.gguf_file = gguf_file
        self.n_ctx = n_ctx
        self._model = None
        self._lock = threading.Lock()
        self._generator = generator
        self._answer_repo = answer_repo
        self._answer_file = answer_file
        self._answer_n_ctx = answer_n_ctx
        self._answer_gpu_layers = answer_gpu_layers

    def _embedder(self):
        with self._lock:
            if self._model is None:
                try:
                    from llama_cpp import Llama
                except ImportError as e:  # pragma: no cover - guidance path
                    raise RuntimeError(
                        "local_embed_backend='llamacpp' needs llama-cpp-python: "
                        "pip install 'lemory[llama]' (or set "
                        "local_embed_backend='fastembed' for the lighter default)"
                    ) from e
                from huggingface_hub import hf_hub_download

                path = hf_hub_download(self.gguf_repo, self.gguf_file)
                self._model = Llama(
                    model_path=path, embedding=True, n_gpu_layers=-1,
                    n_ctx=self.n_ctx, n_batch=512, verbose=False,
                )
            return self._model

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        # raw text both sides (matches the measured 0.853; the query-instruct
        # prefix is unmeasured here, so we do not diverge from the benchmark).
        vecs = self._embedder().embed([t[:6000] for t in texts])
        out = np.asarray(vecs, dtype=np.float32)
        if out.ndim == 1:  # single input can come back 1-D
            out = out[None, :]
        return normalize_embeddings(out)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text], task_type="RETRIEVAL_QUERY")[0]

    # ------------------------------------------------------------- generation
    def generate(self, prompt: str, system: str | None = None, **kw) -> str:
        if self._generator is not None:
            return self._generator.generate(prompt, system=system, **kw)
        from .local import _local_generate
        return _local_generate(prompt, system, self._answer_repo, self._answer_file,
                               self._answer_n_ctx, self._answer_gpu_layers)

    def generate_json(self, prompt: str, system: str | None = None, **kw) -> Any:
        if self._generator is not None:
            return self._generator.generate_json(prompt, system=system, **kw)
        from .base import parse_json_loose
        from .local import _local_generate
        return parse_json_loose(
            _local_generate(prompt, system, self._answer_repo, self._answer_file,
                            self._answer_n_ctx, self._answer_gpu_layers))

    def close(self) -> None:
        if self._generator is not None:
            self._generator.close()
        self._model = None
