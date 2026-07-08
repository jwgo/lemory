"""Hybrid retrieval: dense vectors + BM25 fused with RRF, then knowledge-graph
expansion over note links (wikilinks / unlinked mentions / entities).

Everything here is local and LLM-free, so search is fast (<50ms after the
query embedding) and costs one embedding call per query (cached).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .store import ChunkHit, Store

if TYPE_CHECKING:
    from .config import LemoryConfig
    from .engine import Engine

_WORD_RE = re.compile(r"[a-z0-9]+")

# generic words that shouldn't count as title evidence
_STOP = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "is", "are",
    "was", "were", "what", "which", "who", "whom", "whose", "when", "where",
    "why", "how", "did", "do", "does", "many", "much", "with", "from", "by",
    "at", "as", "that", "this", "it", "its", "be", "been", "not", "no",
}


def _tokens(s: str) -> set[str]:
    return {t for t in _WORD_RE.findall(s.lower()) if t not in _STOP and len(t) > 2}


@dataclass
class SearchResult:
    hits: list[ChunkHit]
    # debug/eval details
    fused: dict[int, float] = field(default_factory=dict)
    expanded_docs: list[int] = field(default_factory=list)


def rrf_fuse(
    ranked_lists: list[tuple[list[tuple[int, float]], float]], rrf_k: int
) -> dict[int, float]:
    """Weighted reciprocal-rank fusion. ranked_lists: [(hits, weight)]."""
    scores: dict[int, float] = {}
    for hits, weight in ranked_lists:
        for rank, (cid, _score) in enumerate(hits):
            scores[cid] = scores.get(cid, 0.0) + weight / (rrf_k + rank + 1)
    return scores


def hybrid_search(
    engine: "Engine",
    query: str,
    k: int = 8,
    graph: bool | None = None,
    mode: str = "hybrid",  # 'hybrid' | 'vector' | 'bm25'  (modes exist for eval/ablation)
) -> SearchResult:
    cfg: "LemoryConfig" = engine.cfg
    store: Store = engine.store
    use_graph = cfg.graph_expansion if graph is None else graph

    vec_hits: list[tuple[int, float]] = []
    bm25_hits: list[tuple[int, float]] = []
    qv = None
    if mode in ("hybrid", "vector"):
        qv = engine.embed_query_cached(query)
        vec_hits = store.vector_search(qv, cfg.k_vector)
    if mode in ("hybrid", "bm25"):
        bm25_hits = store.bm25_search(query, cfg.k_bm25)

    if mode == "vector":
        fused = {cid: 1.0 / (cfg.rrf_k + r + 1) for r, (cid, _) in enumerate(vec_hits)}
    elif mode == "bm25":
        fused = {cid: 1.0 / (cfg.rrf_k + r + 1) for r, (cid, _) in enumerate(bm25_hits)}
    else:
        fused = rrf_fuse([(vec_hits, cfg.w_vector), (bm25_hits, cfg.w_bm25)], cfg.rrf_k)

    if not fused:
        return SearchResult(hits=[])

    chunk_meta = store.get_chunks(fused.keys())

    # --- title boost: a chunk from a note whose title matches query terms is
    # more likely the canonical source (Obsidian notes are entity-titled).
    q_tokens = _tokens(query)
    if mode == "hybrid" and q_tokens and cfg.title_boost > 0:
        for cid, meta in chunk_meta.items():
            t_tokens = _tokens(meta.title)
            if t_tokens and t_tokens <= q_tokens:
                fused[cid] += cfg.title_boost * (len(t_tokens) / max(1, len(q_tokens)))

    expanded_docs: list[int] = []
    if use_graph and mode == "hybrid" and qv is not None:
        expanded_docs = _graph_expand(engine, fused, chunk_meta, qv)
        chunk_meta = store.get_chunks(fused.keys())

    ranked = sorted(fused.items(), key=lambda x: -x[1])

    # per-doc cap keeps the context diverse (supermemory-style); baselines
    # ('vector'/'bm25' modes) stay pure rankings for honest comparison
    cap = cfg.per_doc_cap if mode == "hybrid" else 10**9
    hits: list[ChunkHit] = []
    per_doc: dict[int, int] = {}
    for cid, score in ranked:
        meta = chunk_meta.get(cid)
        if meta is None:
            continue
        if per_doc.get(meta.doc_id, 0) >= cap:
            continue
        per_doc[meta.doc_id] = per_doc.get(meta.doc_id, 0) + 1
        meta.score = score
        hits.append(meta)
        if len(hits) >= k:
            break
    return SearchResult(hits=hits, fused=fused, expanded_docs=expanded_docs)


def _graph_expand(
    engine: "Engine",
    fused: dict[int, float],
    chunk_meta: dict[int, ChunkHit],
    qv,
) -> list[int]:
    """1-hop expansion: pull in the best chunks of notes linked to top hits.

    This is what answers multi-hop questions: the seed hit finds the bridge
    note, the link graph carries the score to the note holding the answer.
    """
    cfg = engine.cfg
    store = engine.store

    doc_best: dict[int, float] = {}
    for cid, s in fused.items():
        meta = chunk_meta.get(cid)
        if meta:
            doc_best[meta.doc_id] = max(doc_best.get(meta.doc_id, 0.0), s)
    top_docs = sorted(doc_best, key=lambda d: -doc_best[d])[: cfg.graph_top_docs]

    neighbor_gain: dict[int, float] = {}
    for src in top_docs:
        for dst, kind, w in store.neighbors([src]).get(src, []):
            gain = cfg.graph_alpha * doc_best[src] * w
            if gain > neighbor_gain.get(dst, 0.0):
                neighbor_gain[dst] = gain

    expanded = []
    for dst, gain in sorted(neighbor_gain.items(), key=lambda x: -x[1]):
        cand_ids = store.doc_chunk_ids(dst)
        if not cand_ids:
            continue
        sims = store.chunk_sims(qv, cand_ids)
        if not sims:
            continue
        best_cid = max(sims, key=sims.get)
        sim = max(sims[best_cid], 0.0)
        add = gain * (0.35 + 0.65 * sim)  # relevance-gated: irrelevant neighbors decay
        if add <= 0:
            continue
        fused[best_cid] = fused.get(best_cid, 0.0) + add
        # runner-up chunk at half strength (long notes may hold the fact deeper)
        rest = {c: s for c, s in sims.items() if c != best_cid}
        if rest:
            second = max(rest, key=rest.get)
            fused[second] = fused.get(second, 0.0) + add * 0.5
        expanded.append(dst)
    return expanded
