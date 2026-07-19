"""LangChain retriever over a Lemory engine.

    from lemory import create_engine
    from lemory.integrations.langchain import LemoryRetriever

    retriever = LemoryRetriever(engine=create_engine(vault="~/Obsidian/MyVault"),
                                k=8)                     # mode="fast" for instant
    docs = retriever.invoke("결제 어떻게 하기로 했지?")

Needs `pip install langchain-core` (not a Lemory dependency)."""

from __future__ import annotations

from typing import Any, List

try:
    from langchain_core.callbacks import CallbackManagerForRetrieverRun
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "LemoryRetriever needs langchain-core: pip install langchain-core"
    ) from e


class LemoryRetriever(BaseRetriever):
    """Hybrid (or fast/vector/bm25) retrieval over the vault as LC Documents."""

    engine: Any
    k: int = 8
    mode: str = "hybrid"

    def _get_relevant_documents(
        self, query: str, *, run_manager: "CallbackManagerForRetrieverRun"
    ) -> List[Document]:
        hits = self.engine.search(query, k=self.k, mode=self.mode)
        return [
            Document(
                page_content=h.text,
                metadata={"path": h.path, "title": h.title, "heading": h.heading,
                          "score": h.score},
            )
            for h in hits
        ]
