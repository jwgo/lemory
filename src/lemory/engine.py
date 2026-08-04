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
        """True when no embedding provider is available · Lemory still runs
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
        client: str = "", fields: dict[str, list[str]] | None = None,
    ) -> list[ChunkHit]:
        from .retrieval import hybrid_search

        hits = hybrid_search(
            self, query, k=k, graph=graph, mode=mode, expand=expand, rerank=rerank,
            fields=fields,
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
            client: str = "", deep: bool = False) -> "Answer":
        from .retrieval import answer

        ans = answer(self, question, k=k, deep=deep)
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

    # ------------------------------------------------------------- the facade
    # Interfaces (CLI/HTTP/MCP/proxy/hooks) call THESE, never the ingestion/
    # retrieval modules directly · enforced by tests/test_architecture.py.
    # Each verb is a thin delegation; the point is a single, stable surface:
    # the engine is the product, the interfaces are adapters around it.

    # ---- notes: write / undo / approve
    def remember_note(self, content: str, **kw):
        from .ingestion.memory import save_memory

        return save_memory(self, content, **kw)

    def append_note(self, path: str, content: str, client: str = "") -> str:
        from .ingestion.memory import append_to_note

        return append_to_note(self, path, content, client=client)

    def trash_note(self, path: str, client: str = "", human: bool = False) -> str:
        from .ingestion.memory import trash_ai_note

        return trash_ai_note(self, path, client=client, human=human)

    def pending_notes(self) -> list[dict]:
        from .ingestion.memory import list_pending

        return list_pending(self)

    def approve_note(self, path: str, client: str = "") -> str:
        from .ingestion.memory import approve_memory

        return approve_memory(self, path, client=client)

    def read_note(self, rel: str) -> str:
        """Full markdown of a vault note (path-guarded)."""
        target = self.safe_path(rel)
        if not target.is_file():
            raise ValueError(f"no such note: {rel}")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_note(self, rel: str, content: str, client: str = "",
                   expect_mtime: float | None = None) -> str:
        """Full-content save of a note · the console editor's verb.

        This is a HUMAN edit surface (the console is the user's own tool),
        so unlike AI writes it may modify existing notes · but with the same
        professionalism a desktop editor ships: path guard, optimistic
        concurrency (`expect_mtime` rejects overwriting a note that changed
        under the editor), git checkpoint when enabled, immediate reindex,
        and an event-log entry so the timeline shows the edit."""
        rel = rel if rel.endswith(".md") else rel + ".md"
        target = self.safe_path(rel)
        if expect_mtime is not None and target.is_file():
            if abs(target.stat().st_mtime - expect_mtime) > 0.001:
                raise ValueError(
                    "conflict: the note changed on disk since it was opened · "
                    "reload before saving")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        rel = str(target.relative_to(self.cfg.resolved_vault()))
        from .ingestion.memory import _git_checkpoint

        _git_checkpoint(self, rel, client or "console", "edit")
        self.index(paths={rel})
        if self.cfg.event_log:
            self.store.log_event("append", client=client or "console", path=rel,
                                 detail={"edit": True, "chars": len(content)})
        return rel

    def rename_note(self, src: str, dst: str, client: str = "") -> str:
        """Move/rename a note within the vault, keeping its history. Both ends
        are path-guarded; the destination must not already exist (no silent
        clobber). Reindexes both paths so search and the graph follow the move.

        Wikilinks that point at the old TITLE keep resolving · they target the
        title, not the path, and only the filename changed. A path-based link
        (rare in Obsidian) would need a vault-wide rewrite, which we
        deliberately don't do here (surprising, destructive); the drift
        scanner surfaces any broken path link afterward."""
        src = src if src.endswith(".md") else src + ".md"
        dst = dst if dst.endswith(".md") else dst + ".md"
        s_target = self.safe_path(src)
        d_target = self.safe_path(dst)
        if not s_target.is_file():
            raise ValueError(f"no such note: {src}")
        if d_target.exists():
            raise ValueError(f"already exists: {dst}")
        d_target.parent.mkdir(parents=True, exist_ok=True)
        s_target.rename(d_target)
        vault = self.cfg.resolved_vault()
        s_rel, d_rel = str(s_target.relative_to(vault)), str(d_target.relative_to(vault))
        # drop the old path from the index, add the new one
        self.store.delete_document(s_rel)
        self.index(paths={d_rel})
        if self.cfg.event_log:
            self.store.log_event("append", client=client or "console", path=d_rel,
                                 detail={"renamed_from": s_rel})
        return d_rel

    def safe_path(self, rel: str) -> "Path":
        """Resolve a vault-relative path, rejecting traversal out of the
        vault. THE path guard · every interface resolves user paths here."""
        from pathlib import Path as _P

        from .ingestion.memory import _safe_target

        return _P(_safe_target(self.cfg.resolved_vault(), rel))

    # ---- agent working memory (typed fragments / threads / anchors)
    def remember(self, content: str, **kw):
        from .ingestion.fragments import remember

        return remember(self, content, **kw)

    def reflect(self, summary: str, **kw):
        from .ingestion.fragments import reflect

        return reflect(self, summary, **kw)

    def set_anchor(self, path: str, on: bool = True, client: str = "") -> str:
        from .ingestion.fragments import set_anchor

        return set_anchor(self, path, on=on, client=client)

    def anchors(self, limit: int = 12) -> list[dict]:
        from .ingestion.fragments import anchored

        return anchored(self, limit=limit)

    def recall(self, query: str = "", **kw) -> list[dict]:
        from .retrieval.recall import recall

        return recall(self, query=query, **kw)

    def resume_case(self, case: str, **kw) -> dict:
        from .retrieval.recall import resume_case

        return resume_case(self, case, **kw)

    def open_cases(self, limit: int = 20) -> list[dict]:
        from .retrieval.recall import open_cases

        return open_cases(self, limit=limit)

    # ---- memory pyramid (L1 → L2 scenes → L3 persona) and skills
    def consolidate(self, use_llm: bool | None = None):
        from .ingestion.pyramid import consolidate

        return consolidate(self, use_llm=use_llm)

    def consolidate_due(self, now: float | None = None) -> bool:
        from .ingestion.pyramid import auto_consolidate_due

        return auto_consolidate_due(self, now=now)

    def scene_map(self, limit: int = 10) -> list[dict]:
        from .ingestion.pyramid import scene_index

        return scene_index(self, limit=limit)

    def persona(self, max_chars: int = 1200) -> str:
        from .ingestion.pyramid import persona_block

        return persona_block(self, max_chars=max_chars)

    def distill(self, **kw) -> list[str]:
        from .ingestion.distill import distill

        return distill(self, **kw)

    def extract_skills(self, cases: "list[str] | None" = None) -> list[str]:
        from .ingestion.skill_extract import extract_skills

        return extract_skills(self, cases=cases)

    def skills(self) -> list[dict]:
        from .ingestion.skill_extract import list_skills

        return list_skills(self)

    # ---- context assembly / discovery
    def context(self, max_chars: int = 2400) -> str:
        from .ingestion.memory import context_block

        return context_block(self, max_chars=max_chars)

    def related(self, path: str, k: int = 8) -> list[dict]:
        from .retrieval.search import related_notes

        return related_notes(self, path, k=k)

    def link_suggestions(self, path: "str | None" = None, k: int = 12) -> list[dict]:
        from .retrieval.links import suggest_links

        return suggest_links(self, path=path, k=k)

    def find_drift(self, **kw):
        from .retrieval.drift import detect_drift

        return detect_drift(self, **kw)

    def drift_repair_prompt(self, findings) -> str:
        from .retrieval.drift import render_repair_prompt

        return render_repair_prompt(findings, str(self.cfg.resolved_vault()))

    def run_connector(self, script, folder: str = ""):
        from .ingestion.connectors import run_connector

        return run_connector(self, script, folder=folder)

    def enrich_entities(self, max_docs: int = 50) -> int:
        from .ingestion import Indexer

        return Indexer(self).enrich_entities(max_docs=max_docs)

    # ---- sessions (chat capture / import)
    def log_session(self, messages: list[dict], answer: str, **kw) -> "str | None":
        from .ingestion.chat_import import log_assistant_session

        return log_assistant_session(self, messages, answer, **kw)

    def import_chats(self, file, folder: str = "chats", limit: "int | None" = None) -> list[str]:
        from .ingestion.chat_import import import_conversations

        return import_conversations(self, file, folder=folder, limit=limit)


def create_engine(**overrides) -> Engine:
    return Engine(load_config(**overrides))
