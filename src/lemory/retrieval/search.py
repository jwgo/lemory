"""Hybrid retrieval: dense vectors + BM25 fused with RRF, then knowledge-graph
expansion over note links (wikilinks / unlinked mentions / entities).

Everything here is local and LLM-free, so search is fast (<50ms after the
query embedding) and costs one embedding call per query (cached).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..storage import ChunkHit, Store
from .temporal import parse_temporal, recency_weight

if TYPE_CHECKING:
    from ..config import LemoryConfig
    from ..engine import Engine

_WORD_RE = re.compile(r"[a-z0-9가-힣]+")

# generic words that shouldn't count as title evidence
_STOP = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "is", "are",
    "was", "were", "what", "which", "who", "whom", "whose", "when", "where",
    "why", "how", "did", "do", "does", "many", "much", "with", "from", "by",
    "at", "as", "that", "this", "it", "its", "be", "been", "not", "no",
}


def _tokens(s: str) -> set[str]:
    return {t for t in _WORD_RE.findall(s.lower()) if t not in _STOP and len(t) > 1}


def _covers(title_tokens: set[str], q_tokens: set[str]) -> bool:
    """Every title token appears in the query — allowing a short trailing
    suffix on the query side so Korean 조사 ('김지수가') still matches the
    title token ('김지수')."""
    return all(
        any(qt == tt or (qt.startswith(tt) and len(qt) <= len(tt) + 2) for qt in q_tokens)
        for tt in title_tokens
    )


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


_ASCII_WORD_RE = re.compile(r"[A-Za-z]{4,}")


def _edit_distance_capped(a: str, b: str, cap: int) -> int:
    """Levenshtein with early exit once the distance must exceed cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
            best = min(best, cur[-1])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def correct_typos(store: Store, query: str) -> str:
    """Local did-you-mean: replace query words that match nothing in the index
    with the closest indexed term (edit distance 1, or 2 for longer words).
    Purely lexical and offline — the vector leg is left on the raw query,
    which embeddings already handle; this repairs the BM25/title-boost legs."""
    lexicon = None
    corrected = query
    for m in _ASCII_WORD_RE.finditer(query):
        word = m.group(0)
        lower = word.lower()
        if store.token_known(lower):
            continue
        if lexicon is None:
            lexicon = store.lexicon()
        cap = 1 if len(lower) <= 5 else 2
        best, best_key = None, (cap + 1, 0)
        for term, doc_count in lexicon.items():
            if term[0] != lower[0] or abs(len(term) - len(lower)) > cap:
                continue
            d = _edit_distance_capped(lower, term, cap)
            if d <= cap and (d, -doc_count) < (best_key[0], -best_key[1]):
                best, best_key = term, (d, doc_count)
        if best:
            corrected = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", best, corrected)
    return corrected


def hybrid_search(
    engine: "Engine",
    query: str,
    k: int = 8,
    graph: bool | None = None,
    mode: str = "hybrid",  # 'hybrid' | 'vector' | 'bm25'  (modes exist for eval/ablation)
    expand: bool | None = None,
    rerank: bool | None = None,
) -> SearchResult:
    cfg: "LemoryConfig" = engine.cfg
    store: Store = engine.store
    use_graph = cfg.graph_expansion if graph is None else graph
    use_expand = (cfg.query_expansion if expand is None else expand) and mode == "hybrid"
    use_rerank = (cfg.rerank if rerank is None else rerank) and mode == "hybrid"

    # local typo repair: the lexical legs (BM25, title boost) die on typos the
    # embedding leg shrugs off; correcting only unknown words is safe because
    # a word that matches the index is never touched
    lex_query = query
    if mode == "hybrid" and cfg.typo_correction:
        lex_query = correct_typos(store, query)

    # qmd-style query expansion: search each LLM-generated variant too, and
    # fuse everything — variants recover vocabulary the note uses but the
    # user's phrasing doesn't. Variants get lower fusion weight than the
    # original query.
    queries = [(query, 1.0, "both")]
    if lex_query != query:
        # corrected text repairs the lexical leg only — no extra embedding call
        queries.append((lex_query, 0.9, "bm25"))
    if use_expand:
        for variant in expand_query(engine, query, cfg.expansion_variants):
            queries.append((variant, 0.6, "both"))

    qv = None
    tagged_lists: list[tuple[str, list[tuple[int, float]], float]] = []
    vec_hits: list[tuple[int, float]] = []
    bm25_hits: list[tuple[int, float]] = []
    for q_text, weight, legs in queries:
        v_hits: list[tuple[int, float]] = []
        b_hits: list[tuple[int, float]] = []
        if mode in ("hybrid", "vector") and legs != "bm25":
            v = engine.embed_query_cached(q_text)
            if q_text == query:
                qv = v
            v_hits = store.vector_search(v, cfg.k_vector)
        if mode in ("hybrid", "bm25"):
            b_hits = store.bm25_search(q_text, cfg.k_bm25)
        if q_text == query:
            vec_hits, bm25_hits = v_hits, b_hits
        tagged_lists.append(("vec", v_hits, cfg.w_vector * weight))
        tagged_lists.append(("bm25", b_hits, cfg.w_bm25 * weight))

    if mode == "vector":
        fused = {cid: 1.0 / (cfg.rrf_k + r + 1) for r, (cid, _) in enumerate(vec_hits)}
    elif mode == "bm25":
        fused = {cid: 1.0 / (cfg.rrf_k + r + 1) for r, (cid, _) in enumerate(bm25_hits)}
    else:
        # adaptive fusion: short keyword-ish queries (a name, a code, a couple
        # of nouns — no question words) are exact-match lookups where the
        # lexical leg is the reliable signal; full questions lean semantic.
        kw_boost = cfg.keyword_bm25_boost if _is_keyword_query(query) else 1.0
        # verbatim questions (phrased with the note's own words — reference-QA
        # style) also deserve a lexical lean: detected per query by how much of
        # the query's vocabulary the top BM25 chunks already cover. Paraphrased,
        # cross-lingual, or typo'd queries have low coverage and are unaffected.
        if kw_boost == 1.0 and bm25_hits:
            cov = _bm25_coverage(store, lex_query, bm25_hits)
            if cov >= cfg.verbatim_gate:
                kw_boost = cfg.keyword_bm25_boost
        fused = rrf_fuse(
            [(hits, w * (kw_boost if kind == "bm25" else 1.0))
             for kind, hits, w in tagged_lists],
            cfg.rrf_k,
        )

    if not fused:
        return SearchResult(hits=[])

    chunk_meta = store.get_chunks(fused.keys())

    # --- recency: "요새 내가 하던 그거 뭐였지?" — when the query signals time
    # (vague recency or an explicit window), newer notes get boosted and notes
    # inside the asked window get boosted hardest. MULTIPLICATIVE on the fused
    # score, so recency amplifies relevance instead of replacing it: a fresh
    # but irrelevant note stays below an on-topic one. Rule-based, zero API.
    if mode == "hybrid" and cfg.recency_boost > 0:
        now_ts = getattr(engine, "now", time.time)()
        intent = parse_temporal(query, now=now_ts)
        if intent.active:
            dates = store.doc_dates()
            doc_of = {cid: m.doc_id for cid, m in chunk_meta.items()}
            for cid in list(fused.keys()):
                ts = dates.get(doc_of.get(cid, -1), 0.0)
                if ts <= 0:
                    continue
                if intent.range_start is not None:
                    in_window = intent.range_start <= ts < (intent.range_end or now_ts)
                    factor = 1.0 + cfg.recency_boost * (2.5 if in_window else 0.0)
                else:
                    w = recency_weight(ts, now_ts, cfg.recency_half_life_days)
                    factor = 1.0 + cfg.recency_boost * w
                fused[cid] *= factor

    # --- title boost: a chunk from a note whose title matches query terms is
    # more likely the canonical source (Obsidian notes are entity-titled).
    # uses the typo-corrected text so a misspelled title still gets its boost
    q_tokens = _tokens(lex_query)
    if mode == "hybrid" and q_tokens and cfg.title_boost > 0:
        for cid, meta in chunk_meta.items():
            t_tokens = _tokens(meta.title)
            if t_tokens and _covers(t_tokens, q_tokens):
                fused[cid] += cfg.title_boost * (len(t_tokens) / max(1, len(q_tokens)))

    expanded_docs: list[int] = []
    if use_graph and mode == "hybrid" and qv is not None:
        expanded_docs = _graph_expand(engine, fused, chunk_meta, qv)
        new_ids = [cid for cid in fused if cid not in chunk_meta]
        if new_ids:  # only fetch what expansion added, not everything again
            chunk_meta.update(store.get_chunks(new_ids))

    # qmd-style LLM rerank: score the top candidates for relevance and blend
    # with the fusion score (costs one LLM call per search)
    if use_rerank and fused:
        _llm_rerank(engine, query, fused, chunk_meta)

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


_QUESTION_WORDS = {
    "what", "which", "who", "when", "where", "why", "how", "did", "does", "do",
    "is", "are", "was", "were",
    "뭐", "뭔가", "무엇", "누구", "언제", "어디", "어디서", "어떻게", "왜", "몇",
}


def _bm25_coverage(store: Store, query: str, bm25_hits: list[tuple[int, float]]) -> float:
    """Fraction of the query's content tokens present in the best-covering
    top-3 BM25 chunk (title included)."""
    q_tokens = _tokens(query)
    if len(q_tokens) < 4:
        return 0.0
    meta = store.get_chunks([cid for cid, _ in bm25_hits[:3]])
    best = 0.0
    for m in meta.values():
        text = (m.text + " " + m.title).lower()
        hit = sum(1 for t in q_tokens if t in text)
        best = max(best, hit / len(q_tokens))
    return best


def _is_keyword_query(query: str) -> bool:
    """True for short lookup-style queries (names/codes/nouns, no question
    words) where exact lexical matching should dominate fusion."""
    words = query.split()
    if len(words) > 4:
        return False
    ql = query.lower()
    return not any(w in ql for w in _QUESTION_WORDS)


def expand_query(engine: "Engine", query: str, n: int) -> list[str]:
    """LLM query expansion (qmd-style). Returns up to n alternative phrasings;
    failures degrade gracefully to no expansion."""
    try:
        data = engine.llm.generate_json(
            "Rewrite this search query for a personal notes database into "
            f"{n} alternative phrasings that use different vocabulary but seek "
            'the same information. Return JSON: {"queries": ["..."]}\n\n'
            f"QUERY: {query}",
            temperature=0.4,
            max_output_tokens=256,
        )
        variants = [v.strip() for v in data.get("queries", []) if isinstance(v, str)]
        return [v for v in variants if v and v.lower() != query.lower()][:n]
    except Exception:
        return []


def _llm_rerank(
    engine: "Engine", query: str, fused: dict[int, float], chunk_meta: dict[int, ChunkHit]
) -> None:
    """Blend LLM relevance scores (0-10) into the fusion scores of the top
    candidates. One LLM call; failures leave the fusion ranking untouched."""
    cfg = engine.cfg
    top = sorted(fused.items(), key=lambda x: -x[1])[: cfg.rerank_top]
    numbered = []
    for i, (cid, _) in enumerate(top, 1):
        meta = chunk_meta.get(cid)
        if meta is None:
            continue
        numbered.append((i, cid, f"[{i}] {meta.title}: {meta.text[:300]}"))
    if not numbered:
        return
    try:
        data = engine.llm.generate_json(
            "Score each passage 0-10 for how well it answers the query. "
            'Return JSON: {"scores": {"1": 7, "2": 0, ...}} covering every number.\n\n'
            f"QUERY: {query}\n\n" + "\n\n".join(t for _, _, t in numbered),
            temperature=0.0,
            max_output_tokens=512,
        )
        scores = data.get("scores", {})
        max_fused = max(fused[cid] for _, cid, _ in numbered) or 1.0
        for i, cid, _ in numbered:
            raw = scores.get(str(i))
            if isinstance(raw, (int, float)):
                llm_score = max(0.0, min(10.0, float(raw))) / 10.0
                fused[cid] = (
                    (1 - cfg.rerank_blend) * fused[cid]
                    + cfg.rerank_blend * llm_score * max_fused
                )
    except Exception:
        pass  # keep fusion ranking


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

    all_nbrs = store.neighbors(top_docs)
    neighbor_gain: dict[int, float] = {}
    for src in top_docs:
        for dst, kind, w in all_nbrs.get(src, []):
            gain = cfg.graph_alpha * doc_best[src] * w
            if gain > neighbor_gain.get(dst, 0.0):
                neighbor_gain[dst] = gain

    chunk_ids_by_doc = store.doc_chunk_ids_many(list(neighbor_gain))
    all_sims = store.chunk_sims(qv, [c for ids in chunk_ids_by_doc.values() for c in ids])

    # expansion may fill ranks 2..k but must never displace the best direct
    # hit: multi-hop only needs the neighbor IN the top-k, while single-hop
    # precision depends on rank-1 staying with the direct evidence
    top_direct = max(fused.values(), default=0.0)
    cap = top_direct * 0.98

    expanded = []
    for dst, gain in sorted(neighbor_gain.items(), key=lambda x: -x[1]):
        sims = {c: all_sims[c] for c in chunk_ids_by_doc.get(dst, []) if c in all_sims}
        if not sims:
            continue
        best_cid = max(sims, key=sims.get)
        sim = max(sims[best_cid], 0.0)
        if sim < cfg.graph_sim_floor:
            # neighbor's content has nothing to do with the query: linked-but-
            # irrelevant notes must not displace direct hits (single-hop safety)
            continue
        add = gain * (0.35 + 0.65 * sim)  # relevance-gated: irrelevant neighbors decay
        if add <= 0:
            continue
        fused[best_cid] = min(fused.get(best_cid, 0.0) + add, cap)
        # runner-up chunk at half strength (long notes may hold the fact deeper)
        rest = {c: s for c, s in sims.items() if c != best_cid}
        if rest:
            second = max(rest, key=rest.get)
            fused[second] = min(fused.get(second, 0.0) + add * 0.5, cap)
        expanded.append(dst)
    return expanded
