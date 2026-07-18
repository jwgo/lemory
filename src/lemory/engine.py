"""Engine: the object that owns config, storage, and the LLM provider client."""

from __future__ import annotations

import threading
from typing import Any, Optional

import numpy as np

from .config import LemoryConfig, load_config
from .providers import LLMClient, create_client
from .storage import ChunkHit, Store


class Engine:
    def __init__(self, cfg: LemoryConfig, llm=None, store: Optional[Store] = None):
        self.cfg = cfg
        self.store = store or Store(
            cfg.resolved_data_dir() / "lemory.db",
            ann_threshold=cfg.ann_threshold if cfg.ann_threshold > 0 else 2**62,
            ann_nprobe=cfg.ann_nprobe,
        )
        self._llm = llm
        self._indexer = None
        # serializes sync runs: the server's watcher thread and POST /index
        # (or any two callers) must never interleave chunk/link mutations
        self._index_lock = threading.Lock()

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = create_client(self.cfg)
        return self._llm

    # ------------------------------------------------------------ embeddings
    def embed_documents_cached(self, texts: list[str]) -> tuple[np.ndarray, int]:
        """Embed with content-hash cache. Returns (vectors, api_misses)."""
        model, dim = self.cfg.active_embed_model(), self.cfg.active_embed_dim()
        keys = [Store.cache_key(model, dim, "doc", t) for t in texts]
        cached = self.store.cache_get_many(keys)
        out = np.zeros((len(texts), dim), dtype=np.float32)
        missing_idx = []
        for i, k in enumerate(keys):
            if k in cached and cached[k].shape[0] == dim:
                out[i] = cached[k]
            else:
                missing_idx.append(i)
        if missing_idx:
            import time as _time

            t0 = _time.monotonic()
            fresh = self.llm.embed([texts[i] for i in missing_idx], task_type="RETRIEVAL_DOCUMENT")
            elapsed = _time.monotonic() - t0
            put = {}
            for j, i in enumerate(missing_idx):
                out[i] = fresh[j]
                put[keys[i]] = fresh[j]
            self.store.cache_put_many(put)
            # remember observed embed throughput → index-time estimates (EMA)
            if elapsed > 0.05 and len(missing_idx) >= 8:
                rate = len(missing_idx) / elapsed
                old = self.store.get_meta("embed_rate_ema")
                ema = rate if old is None else 0.7 * float(old) + 0.3 * rate
                self.store.set_meta("embed_rate_ema", f"{ema:.2f}")
        return out, len(missing_idx)

    def embed_query_cached(self, query: str) -> np.ndarray:
        key = Store.cache_key(self.cfg.active_embed_model(), self.cfg.active_embed_dim(), "query", query)
        cached = self.store.cache_get_many([key])
        if key in cached and cached[key].shape[0] == self.cfg.active_embed_dim():
            return cached[key]
        vec = self.llm.embed([query], task_type="RETRIEVAL_QUERY")[0]
        self.store.cache_put_many({key: vec})
        return vec

    # ----------------------------------------------------------------- verbs
    def index_plan(self, full: bool = False):
        """Dry-run: what would index() process, and roughly how long?"""
        from .ingestion import Indexer

        with self._index_lock:
            if self._indexer is None:
                self._indexer = Indexer(self)
            return self._indexer.plan(full=full)

    @property
    def keyless(self) -> bool:
        """True when no embedding provider is available — Lemory still runs
        (BM25 + typo repair + boosts + operators), just without the vector leg.
        Adding a key later upgrades in place: the next index embeds everything."""
        try:
            self.cfg.resolved_provider()
            return False
        except RuntimeError:
            return True

    def index(self, full: bool = False, progress=None, paths: Optional[set] = None):
        from .ingestion import Indexer

        with self._index_lock:
            # vectors from different embedding models live in different spaces —
            # comparing them silently returns garbage. Detect a model/dim switch
            # and force a full re-embed (old cache entries are keyed by model,
            # so switching BACK later is free).
            if not self.keyless:
                sig = f"{self.cfg.active_embed_model()}|{self.cfg.active_embed_dim()}"
                stored = self.store.get_meta("embed_signature")
                import logging

                _log = logging.getLogger("lemory.engine")
                if stored is not None and stored != sig and self.store.chunk_count() > 0:
                    _log.warning(
                        "embedding model changed (%s -> %s): re-embedding the whole "
                        "vault so search stays correct", stored, sig,
                    )
                    full = True
                    paths = None
                elif self.store.unembedded_chunk_count() > 0:
                    # keyless→keyed upgrade: notes indexed without a provider have
                    # NULL vectors. An incremental sync would only touch changed
                    # files, leaving old notes permanently invisible to vector
                    # search. Force a full pass so every note gets embedded.
                    _log.info("provider now available: embedding %d chunks left "
                              "from a keyless index",
                              self.store.unembedded_chunk_count())
                    full = True
                    paths = None
            else:
                sig = None
                stored = self.store.get_meta("embed_signature")
                if stored is not None and self.store.chunk_count() > 0:
                    # a key existed before and is gone now: keep the old vectors,
                    # they are still valid — just don't claim a fresh signature
                    sig = stored

            if self._indexer is None:
                self._indexer = Indexer(self)
            rep = self._indexer.sync(full=full, progress=progress, paths=paths)
            if sig is not None:
                self.store.set_meta("embed_signature", sig)
            if self.cfg.enrich_entities and not self.keyless:
                self._indexer.enrich_entities()
            # warm the query-path lexical structures (typo lexicon + first/
            # second-char buckets) in the background: on a large vault the
            # first search would otherwise pay a full-vocabulary scan inline
            # (~1-2s on 30k+ chunks). Writes invalidate them, so re-warm after
            # each sync. Daemon thread, errors swallowed — purely a cache.
            if self.store.chunk_count() > 5000:
                import threading

                threading.Thread(target=self._warm_lexicon, daemon=True).start()
            return rep

    def _warm_lexicon(self) -> None:
        try:
            self.store.lexicon_buckets()
        except Exception:
            pass

    def watch(self, on_sync=None) -> None:
        from .ingestion import watch as _watch

        self.index()
        _watch(self, on_sync=on_sync)

    def search(
        self, query: str, k: int = 8, graph: bool | None = None, mode: str = "hybrid",
        expand: bool | None = None, rerank: bool | None = None, record: bool = False,
        client: str = "",
    ) -> list[ChunkHit]:
        from .retrieval import hybrid_search

        hits = hybrid_search(
            self, query, k=k, graph=graph, mode=mode, expand=expand, rerank=rerank
        ).hits
        # hit stats are opt-in per call site: the server and CLI record real
        # usage; library calls, tests and benchmarks stay invisible
        if record and hits:
            self.store.record_hits([h.doc_id for h in hits])
        if record and self.cfg.event_log:
            self.store.log_event("search", client=client, query=query,
                                 detail={"top": [h.path for h in hits[:3]]})
        return hits

    def ask(self, question: str, k: int = 8, record: bool = False,
            client: str = "") -> "Answer":
        from .retrieval import answer

        ans = answer(self, question, k=k)
        if record and ans.sources:
            self.store.record_hits([h.doc_id for h in ans.sources])
        if record and self.cfg.event_log:
            self.store.log_event("ask", client=client, query=question,
                                 detail={"top": [h.path for h in ans.sources[:3]]})
        return ans

    def conflicts(self, threshold: float = 0.80, limit: int = 30):
        """Cross-note disagreement scan (numbers/negation/duplicates). Local."""
        from .retrieval import find_conflicts

        return find_conflicts(self, threshold=threshold, limit=limit)

    def status(self) -> dict[str, Any]:
        # status is a purely local verb — it must work without any API key
        try:
            embed_model = f"{self.cfg.active_embed_model()} ({self.cfg.active_embed_dim()}d)"
            llm_model = self.cfg.active_llm_model()
        except RuntimeError:
            embed_model = llm_model = "unconfigured (no API key)"
        return {
            "vault": str(self.cfg.vault) if self.cfg.vault else None,
            "db": str(self.store.db_path),
            "documents": self.store.doc_count(),
            "chunks": self.store.chunk_count(),
            "links": self.store.link_count(),
            "vector_index": self.store.vector_index_kind(),
            "embed_model": embed_model,
            "llm_model": llm_model,
            "last_sync": self.store.get_meta("last_sync"),
        }

    def close(self) -> None:
        self.store.close()
        if self._llm is not None:
            self._llm.close()


def create_engine(**overrides) -> Engine:
    return Engine(load_config(**overrides))
