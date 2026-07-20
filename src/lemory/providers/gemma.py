"""On-device answer LLM on the **same llama.cpp engine** as the embedder and the
reranker · one runtime (Metal / CUDA / Vulkan / CPU offload), no daemon, no
second engine. Runs **Gemma 4** (E4B by default, E2B for lighter machines) from
a Q4 GGUF; the model auto-downloads from HuggingFace once and is cached, and
the context easily holds the retrieved NOTES (Gemma 4 supports a large window).

    pip install "lemory[llama]"
"""
from __future__ import annotations

import threading

DEFAULT_REPO = "ggml-org/gemma-4-E4B-it-GGUF"
DEFAULT_FILE = "gemma-4-E4B-it-Q4_0.gguf"

# selectable sizes: E4B (Google's recommended, default) and E2B (lighter/faster).
# ggml-org's E4B repo ships Q4_0 (not Q4_K_M); unsloth's E2B ships the full
# quant ladder. If a pinned filename ever 404s (repo re-quantized/renamed),
# _model() self-heals by listing the repo and picking an available quant.
MODELS = {
    "E2B": ("unsloth/gemma-4-E2B-it-GGUF", "gemma-4-E2B-it-Q4_K_M.gguf"),
    "E4B": ("ggml-org/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-Q4_0.gguf"),
}

# preferred quant order when a pinned file is missing — good size/quality
# balance first, never the mmproj/mtp side-car files.
_QUANT_ORDER = ("Q4_K_M", "Q4_0", "Q4_K_S", "Q4_1", "Q5_K_M", "Q8_0")

N_CTX = 8192  # holds the RAG NOTES + question + answer comfortably

_MODELS: dict = {}
_LOAD_LOCK = threading.Lock()
_GEN_LOCK = threading.Lock()  # one decode at a time (single local model instance)


def available() -> tuple[bool, str]:
    from importlib.util import find_spec
    if find_spec("llama_cpp") is not None:
        return True, ""
    return False, '답변 모델(llama.cpp)이 설치되지 않았습니다: pip install "lemory[llama]"'


def _resolve_gguf(repo: str, file: str) -> str:
    """Download `file` from `repo`; if it 404s (repo re-quantized or renamed the
    pinned file), list the repo's GGUFs and pick the best available quant so a
    single upstream rename never hard-crashes on-device answering."""
    from huggingface_hub import hf_hub_download

    try:
        return hf_hub_download(repo, file)
    except Exception:
        from huggingface_hub import HfApi

        try:
            names = [s for s in HfApi().list_repo_files(repo) if s.endswith(".gguf")]
        except Exception:
            raise  # can't reach the repo at all → surface the original error
        # never the multimodal-projector / multi-token-prediction side-cars
        cands = [n for n in names
                 if "mmproj" not in n.lower() and "/mtp" not in n.lower()
                 and not n.lower().startswith("mtp")]
        for quant in _QUANT_ORDER:
            for n in cands:
                if quant.lower() in n.lower():
                    return hf_hub_download(repo, n)
        if cands:  # last resort: any non-sidecar gguf
            return hf_hub_download(repo, sorted(cands)[0])
        raise


def _model(repo: str, file: str, n_ctx: int = N_CTX, gpu_layers: int = -1):
    key = (repo, file, n_ctx, gpu_layers)  # distinct runtime configs don't collide
    with _LOAD_LOCK:
        m = _MODELS.get(key)
        if m is None:
            from llama_cpp import Llama

            path = _resolve_gguf(repo, file)
            m = Llama(model_path=path, n_gpu_layers=gpu_layers, n_ctx=n_ctx,
                      chat_format="gemma", verbose=False)
            _MODELS[key] = m
        return m


def _fit(llm, system: str, history: list[dict], question: str,
         max_output_tokens: int) -> tuple[str, list[dict]]:
    """Fit (grounding, history, question) into the window with the RIGHT
    priority: the freshly-retrieved NOTES are the answer's evidence, so they
    outrank stale chat turns. Order of sacrifice as the context fills:

        1. keep the question (always) and the answer budget,
        2. keep the grounding NOTES (trim their tail only if they alone are huge
           · build_context orders by rank, so the tail is least relevant),
        3. fill whatever budget remains with the MOST RECENT history turns,
           dropping the oldest first (sliding window).

    The old code did the opposite · it trimmed the grounding to make room for
    history · so a long conversation slowly starved retrieval and later turns
    lost their evidence. Returns (grounding, kept_history)."""
    def toks(s: str) -> int:
        return len(llm.tokenize(s.encode("utf-8")))

    try:
        ctx = llm.n_ctx()
        budget = ctx - max_output_tokens - toks(question) - 160
        if budget < 256:
            budget = 256
        # grounding gets up to ~75% of the budget; question always survives
        ids = llm.tokenize(system.encode("utf-8"))
        gcap = max(256, int(budget * 0.75))
        if len(ids) > gcap:
            system = llm.detokenize(ids[:gcap]).decode("utf-8", "ignore")
            gtok = gcap
        else:
            gtok = len(ids)
        # fill the remainder with the newest history turns, oldest dropped first
        remain = budget - gtok
        kept: list[dict] = []
        for m in reversed(history):
            c = str(m.get("content", ""))
            t = toks(c) + 8
            if t > remain:
                break
            kept.insert(0, m)
            remain -= t
        return system, kept
    except Exception:
        return system[:6000], history[-2:]


def chat_stream(system: str, history: list[dict], question: str,
                repo: str = DEFAULT_REPO, file: str = DEFAULT_FILE,
                max_output_tokens: int = 512,
                n_ctx: int = N_CTX, gpu_layers: int = -1):
    """Yield answer text deltas, grounded via `system` and continued from
    `history` (a list of {"role","content"} for prior turns)."""
    llm = _model(repo, file, n_ctx, gpu_layers)
    hist = [{"role": m["role"], "content": str(m["content"])}
            for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
    with _GEN_LOCK:
        system, hist = _fit(llm, system, hist, question, max_output_tokens)
        # Gemma's chat template has NO system role — llama.cpp's `format_gemma`
        # drops a {"role":"system"} message entirely. Fold the grounding NOTES
        # into the current user turn so retrieval actually reaches the model.
        user = f"{system}\n\n{question}" if system else question
        messages = hist + [{"role": "user", "content": user}]
        for chunk in llm.create_chat_completion(
                messages, max_tokens=max_output_tokens, stream=True):
            delta = chunk["choices"][0]["delta"].get("content")
            if delta:
                yield delta


def generate(system: str, question: str, repo: str = DEFAULT_REPO,
             file: str = DEFAULT_FILE, max_output_tokens: int = 512,
             n_ctx: int = N_CTX, gpu_layers: int = -1) -> str:
    """Non-streaming grounded answer (for engine.ask / the search view), so a
    keyless local install can answer on-device without any API key or daemon."""
    return "".join(chat_stream(system, [], question, repo=repo, file=file,
                               max_output_tokens=max_output_tokens,
                               n_ctx=n_ctx, gpu_layers=gpu_layers)).strip()
