"""In-process cross-encoder reranker via fastembed (ONNX), no daemon. Default
model is jina-reranker-v2-base-multilingual, strong on Korean, so `reranker`
mode reorders candidates on-device with no Ollama. fastembed is a base
dependency, so this is always available."""
from __future__ import annotations

import threading

DEFAULT_MODEL = "jinaai/jina-reranker-v2-base-multilingual"

_MODELS: dict = {}
_LOCK = threading.Lock()


def available() -> bool:
    from importlib.util import find_spec
    return find_spec("fastembed") is not None


def _encoder(model: str):
    with _LOCK:
        ce = _MODELS.get(model)
        if ce is None:
            import warnings

            from fastembed.rerank.cross_encoder import TextCrossEncoder

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ce = TextCrossEncoder(model_name=model)
            _MODELS[model] = ce
        return ce


def rerank_scores(query: str, docs: list[str], model: str = DEFAULT_MODEL) -> list[float]:
    """Relevance scores (higher = more relevant) for each doc against the query."""
    if not docs:
        return []
    return [float(s) for s in _encoder(model).rerank(query, docs)]
