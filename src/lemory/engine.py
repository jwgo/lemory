"""Engine: the object that owns config, storage, and the Gemini client."""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .config import LemoryConfig, load_config
from .gemini import GeminiClient
from .store import ChunkHit, Store

log = logging.getLogger("lemory.engine")


class Engine:
    def __init__(self, cfg: LemoryConfig, llm: Optional[GeminiClient] = None, store: Optional[Store] = None):
        self.cfg = cfg
        self.store = store or Store(cfg.resolved_data_dir() / "lemory.db")
        self._llm = llm
        self._indexer = None

    @property
    def llm(self) -> GeminiClient:
        if self._llm is None:
            self._llm = GeminiClient(
                api_key=self.cfg.resolved_api_key(),
                llm_model=self.cfg.llm_model,
                llm_fallback_model=self.cfg.llm_fallback_model,
                llm_rpm=self.cfg.llm_rpm,
                embed_model=self.cfg.embed_model,
                embed_dim=self.cfg.embed_dim,
                embed_rpm=self.cfg.embed_rpm,
                max_output_tokens=self.cfg.llm_max_output_tokens,
            )
        return self._llm

    # ------------------------------------------------------------ embeddings
    def embed_documents_cached(self, texts: list[str]) -> tuple[np.ndarray, int]:
        """Embed with content-hash cache. Returns (vectors, api_misses)."""
        keys = [Store.cache_key(self.cfg.embed_model, self.cfg.embed_dim, "doc", t) for t in texts]
        cached = self.store.cache_get_many(keys)
        out = np.zeros((len(texts), self.cfg.embed_dim), dtype=np.float32)
        missing_idx = []
        for i, k in enumerate(keys):
            if k in cached and cached[k].shape[0] == self.cfg.embed_dim:
                out[i] = cached[k]
            else:
                missing_idx.append(i)
        if missing_idx:
            fresh = self.llm.embed([texts[i] for i in missing_idx], task_type="RETRIEVAL_DOCUMENT")
            put = {}
            for j, i in enumerate(missing_idx):
                out[i] = fresh[j]
                put[keys[i]] = fresh[j]
            self.store.cache_put_many(put)
        return out, len(missing_idx)

    def embed_query_cached(self, query: str) -> np.ndarray:
        key = Store.cache_key(self.cfg.embed_model, self.cfg.embed_dim, "query", query)
        cached = self.store.cache_get_many([key])
        if key in cached and cached[key].shape[0] == self.cfg.embed_dim:
            return cached[key]
        vec = self.llm.embed([query], task_type="RETRIEVAL_QUERY")[0]
        self.store.cache_put_many({key: vec})
        return vec

    # ----------------------------------------------------------------- verbs
    def index(self, full: bool = False, progress=None):
        from .ingest import Indexer

        if self._indexer is None:
            self._indexer = Indexer(self)
        rep = self._indexer.sync(full=full, progress=progress)
        if self.cfg.enrich_entities:
            self._indexer.enrich_entities()
        return rep

    def watch(self, on_sync=None) -> None:
        from .ingest import watch as _watch

        self.index()
        _watch(self, on_sync=on_sync)

    def search(self, query: str, k: int = 8, graph: bool | None = None, mode: str = "hybrid") -> list[ChunkHit]:
        from .search import hybrid_search

        return hybrid_search(self, query, k=k, graph=graph, mode=mode).hits

    def ask(self, question: str, k: int = 8) -> "Answer":
        from .answer import answer

        return answer(self, question, k=k)

    def status(self) -> dict[str, Any]:
        return {
            "vault": str(self.cfg.vault) if self.cfg.vault else None,
            "db": str(self.store.db_path),
            "documents": self.store.doc_count(),
            "chunks": self.store.chunk_count(),
            "links": self.store.link_count(),
            "embed_model": f"{self.cfg.embed_model} ({self.cfg.embed_dim}d)",
            "llm_model": self.cfg.llm_model,
            "last_sync": self.store.get_meta("last_sync"),
        }

    def close(self) -> None:
        self.store.close()
        if self._llm is not None:
            self._llm.close()


def create_engine(**overrides) -> Engine:
    return Engine(load_config(**overrides))
