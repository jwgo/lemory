"""On-device answer LLM on the **same llama.cpp engine** as the embedder and the
reranker — one runtime (Metal / CUDA / Vulkan / CPU offload), no daemon, no
second engine. Runs **Gemma 4** (E4B by default, E2B for lighter machines) from
a Q4_K_M GGUF; the model auto-downloads from HuggingFace once and is cached, and
the context easily holds the retrieved NOTES (Gemma 4 supports a large window).

    pip install "lemory[llama]"
"""
from __future__ import annotations

import threading

DEFAULT_REPO = "ggml-org/gemma-4-E4B-it-GGUF"
DEFAULT_FILE = "gemma-4-E4B-it-Q4_K_M.gguf"

# selectable sizes: E4B (Google's recommended, default) and E2B (lighter/faster).
# Both Q4 GGUFs; ggml-org ships E4B Q4_K_M, unsloth ships the E2B Q4.
MODELS = {
    "E2B": ("unsloth/gemma-4-E2B-it-GGUF", "gemma-4-E2B-it-Q4_0.gguf"),
    "E4B": ("ggml-org/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_K_M.gguf"),
}

N_CTX = 8192  # holds the RAG NOTES + question + answer comfortably

_MODELS: dict = {}
_LOAD_LOCK = threading.Lock()
_GEN_LOCK = threading.Lock()  # one decode at a time (single local model instance)


def available() -> tuple[bool, str]:
    from importlib.util import find_spec
    if find_spec("llama_cpp") is not None:
        return True, ""
    return False, '답변 모델(llama.cpp)이 설치되지 않았습니다: pip install "lemory[llama]"'


def _model(repo: str, file: str):
    key = (repo, file)
    with _LOAD_LOCK:
        m = _MODELS.get(key)
        if m is None:
            from huggingface_hub import hf_hub_download
            from llama_cpp import Llama

            path = hf_hub_download(repo, file)
            m = Llama(model_path=path, n_gpu_layers=-1, n_ctx=N_CTX,
                      chat_format="gemma", verbose=False)
            _MODELS[key] = m
        return m


def _fit_system(llm, system: str, history: list[dict], question: str,
                max_output_tokens: int) -> str:
    """Trim the grounding NOTES (system) so the whole prompt fits n_ctx — RAG
    contexts can exceed the window, and build_context orders notes by rank, so
    dropping the tail loses the least-relevant grounding."""
    try:
        used = len(llm.tokenize(question.encode("utf-8"))) + sum(
            len(llm.tokenize(str(m.get("content", "")).encode("utf-8"))) for m in history)
        keep = N_CTX - max_output_tokens - used - 128
        if keep < 256:
            keep = 256
        ids = llm.tokenize(system.encode("utf-8"))
        if len(ids) > keep:
            return llm.detokenize(ids[:keep]).decode("utf-8", "ignore")
    except Exception:
        return system[:9000]
    return system


def chat_stream(system: str, history: list[dict], question: str,
                repo: str = DEFAULT_REPO, file: str = DEFAULT_FILE,
                max_output_tokens: int = 512):
    """Yield answer text deltas, grounded via `system` and continued from
    `history` (a list of {"role","content"} for prior turns)."""
    llm = _model(repo, file)
    hist = [{"role": m["role"], "content": str(m["content"])}
            for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
    with _GEN_LOCK:
        system = _fit_system(llm, system, hist, question, max_output_tokens)
        messages = ([{"role": "system", "content": system}] if system else []) + \
            hist + [{"role": "user", "content": question}]
        for chunk in llm.create_chat_completion(
                messages, max_tokens=max_output_tokens, stream=True):
            delta = chunk["choices"][0]["delta"].get("content")
            if delta:
                yield delta


def generate(system: str, question: str, repo: str = DEFAULT_REPO,
             file: str = DEFAULT_FILE, max_output_tokens: int = 512) -> str:
    """Non-streaming grounded answer (for engine.ask / the search view), so a
    keyless local install can answer on-device without any API key or daemon."""
    return "".join(chat_stream(system, [], question, repo=repo, file=file,
                               max_output_tokens=max_output_tokens)).strip()
