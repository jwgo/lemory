"""On-device assistant brain via Google LiteRT-LM: Gemma 4 E2B in the
`.litertlm` format, the same runtime + model parlor uses. Fully in-process,
no daemon, no Ollama. The model (~2.6GB) auto-downloads from HuggingFace once
and is cached; the Engine loads once (~3s) and is reused.

    pip install "lemory[assistant]"
"""
from __future__ import annotations

import threading

DEFAULT_REPO = "litert-community/gemma-4-E2B-it-litert-lm"
DEFAULT_FILE = "gemma-4-E2B-it.litertlm"

_ENGINES: dict = {}
_LOAD_LOCK = threading.Lock()
_GEN_LOCK = threading.Lock()  # one decode at a time (single local model instance)


def available() -> tuple[bool, str]:
    try:
        import litert_lm  # noqa: F401
        return True, ""
    except ImportError:
        return False, ('비서 브레인(LiteRT-LM)이 설치되지 않았습니다: '
                       'pip install "lemory[assistant]"')


def _engine(repo: str, file: str):
    key = (repo, file)
    with _LOAD_LOCK:
        eng = _ENGINES.get(key)
        if eng is None:
            from huggingface_hub import hf_hub_download
            from litert_lm import Backend, Engine

            path = hf_hub_download(repo, file)
            eng = Engine(path, backend=Backend.CPU())
            _ENGINES[key] = eng
        return eng


def chat_stream(system: str, history: list[dict], question: str,
                repo: str = DEFAULT_REPO, file: str = DEFAULT_FILE,
                max_output_tokens: int = 512):
    """Yield answer text deltas, grounded via `system` and continued from
    `history` (a list of {"role","content"} for prior turns)."""
    eng = _engine(repo, file)
    msgs = [{"role": m["role"], "content": str(m["content"])}
            for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
    with _GEN_LOCK:
        conv = eng.create_conversation(system_message=system, messages=msgs or None,
                                       max_output_tokens=max_output_tokens)
        for chunk in conv.send_message_async(question):
            content = chunk.get("content")
            if isinstance(content, list):
                txt = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                if txt:
                    yield txt
            elif isinstance(content, str) and content:
                yield content
