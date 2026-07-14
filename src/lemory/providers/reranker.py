"""In-process cross-encoder reranker on the **same llama.cpp engine** as the
embedder and the answer LLM — one runtime (Metal / CUDA / Vulkan / CPU offload),
no fastembed, no daemon.

Runs **Qwen3-Reranker-0.6B** (2025 SOTA small reranker) by its official yes/no
method: the query+document are formatted with the reranker template and the
model's next-token distribution is read — `P("yes")` is the relevance score.
The GGUF (~600 MB) auto-downloads from HuggingFace once and is cached.
"""
from __future__ import annotations

import math
import threading

import numpy as np

DEFAULT_REPO = "dengcao/Qwen3-Reranker-0.6B-GGUF"
DEFAULT_FILE = "Qwen3-Reranker-0.6B-q8_0.gguf"

# Qwen3-Reranker single-token verdict ids in the Qwen tokenizer.
_YES_ID = 9693
_NO_ID = 2152
_PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements '
           'based on the Query and the Instruct provided. Note that the answer can '
           'only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
_SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
_INSTRUCT = 'Given a web search query, retrieve relevant passages that answer the query'

_MODELS: dict = {}
_LOCK = threading.Lock()


def available() -> bool:
    from importlib.util import find_spec
    return find_spec("llama_cpp") is not None


def _model(repo: str, file: str):
    key = (repo, file)
    m = _MODELS.get(key)
    if m is None:
        from huggingface_hub import hf_hub_download
        from llama_cpp import Llama

        path = hf_hub_download(repo, file)
        # logits_all=False keeps prefill cheap (no full-vocab projection for
        # every position); we read only the last token's logits via the C
        # accessor below. n_gpu_layers=-1 offloads all layers to the GPU.
        # ~57 ms/candidate on Metal vs ~290 ms with logits_all=True.
        m = Llama(model_path=path, n_gpu_layers=-1, n_ctx=2048,
                  logits_all=False, verbose=False)
        _MODELS[key] = m
    return m


def _score(llm, query: str, doc: str) -> float:
    import llama_cpp

    prompt = (_PREFIX + f'<Instruct>: {_INSTRUCT}\n<Query>: {query}\n<Document>: {doc}'
              + _SUFFIX)
    tokens = llm.tokenize(prompt.encode("utf-8"), add_bos=True)
    llm.reset()
    llm.eval(tokens)
    # last-token logits straight from the context (computed even without
    # logits_all); avoids materializing the whole (n_tokens x vocab) matrix
    ptr = llama_cpp.llama_get_logits_ith(llm._ctx.ctx, -1)
    logits = np.ctypeslib.as_array(ptr, shape=(llm.n_vocab(),))
    yes, no = float(logits[_YES_ID]), float(logits[_NO_ID])
    m = max(yes, no)
    ey, en = math.exp(yes - m), math.exp(no - m)
    return ey / (ey + en)


def rerank_scores(query: str, docs: list[str], repo: str = DEFAULT_REPO,
                  file: str = DEFAULT_FILE) -> list[float]:
    """Relevance scores in [0,1] (P("yes"), higher = more relevant) for each doc.
    Serialized on one llama.cpp context — a local single user reranks a handful
    of candidates per query."""
    if not docs:
        return []
    with _LOCK:
        llm = _model(repo, file)
        # cap each candidate so the query+doc prompt stays well within n_ctx
        return [_score(llm, query, d[:1600]) for d in docs]
