"""LlamaIndex retriever over a Lemory engine.

    from lemory import create_engine
    from lemory.integrations.llamaindex import LemoryLlamaRetriever

    retriever = LemoryLlamaRetriever(create_engine(vault="~/Obsidian/MyVault"), k=8)
    nodes = retriever.retrieve("결제 어떻게 하기로 했지?")

Needs `pip install llama-index-core` (not a Lemory dependency)."""

from __future__ import annotations

from typing import Any, List

try:
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "LemoryLlamaRetriever needs llama-index-core: pip install llama-index-core"
    ) from e


class LemoryLlamaRetriever(BaseRetriever):
    def __init__(self, engine: Any, k: int = 8, mode: str = "hybrid") -> None:
        self._engine = engine
        self._k = k
        self._mode = mode
        super().__init__()

    def _retrieve(self, query_bundle: "QueryBundle") -> List["NodeWithScore"]:
        hits = self._engine.search(query_bundle.query_str, k=self._k, mode=self._mode)
        return [
            NodeWithScore(
                node=TextNode(
                    text=h.text,
                    metadata={"path": h.path, "title": h.title, "heading": h.heading},
                ),
                score=float(h.score),
            )
            for h in hits
        ]
