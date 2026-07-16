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


# khoj-style scoping operators: `tag:프로젝트 folder:회의록 예산 결정` restricts
# retrieval before ranking. Values with spaces are quoted: tag:"프로젝트 A".
_OPERATOR_RE = re.compile(r'(?:^|\s)(tag|folder|path)\s*:\s*(?:"([^"]+)"|(\S+))',
                          re.IGNORECASE)


def parse_operators(query: str) -> tuple[str, list[str], list[str]]:
    """Split scoping operators out of a query.

    Returns (clean_query, tags, folders). Multiple tags AND together; multiple
    folders OR together (two disjoint folders can never AND). `path:` is a
    synonym for `folder:`."""
    tags: list[str] = []
    folders: list[str] = []

    def _grab(m: re.Match) -> str:
        val = (m.group(2) or m.group(3)).strip().lstrip("#")
        if val:
            (tags if m.group(1).lower() == "tag" else folders).append(val)
        return " "

    clean = _OPERATOR_RE.sub(_grab, query).strip()
    return clean, tags, folders


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
_HANGUL_WORD_RE = re.compile(r"[가-힣]{3,}")


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


def _dl_distance_capped(a: str, b: str, cap: int) -> int:
    """Damerau-Levenshtein (adjacent transposition = 1 op) with cap exit.

    For Hangul the unit is the SYLLABLE — a fat-finger swap ('메이플' →
    '메플이') is one operation, matching how Korean typos actually happen;
    plain Levenshtein would charge 2 and push real typos past the cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            d = min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb))
            if (prev2 is not None and i > 1 and j > 1
                    and ca == b[j - 2] and a[i - 2] == cb):
                d = min(d, prev2[j - 2] + 1)
            cur.append(d)
            best = min(best, d)
        if best > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


def correct_typos(store: Store, query: str) -> str:
    """Local did-you-mean: replace query words that match nothing in the index
    with the closest indexed term. Purely lexical and offline — the vector leg
    is left on the raw query, which embeddings already handle; this repairs
    the BM25/title-boost legs.

    ASCII words: Levenshtein (distance 1, or 2 for longer words).
    Hangul words: syllable-level Damerau-Levenshtein — an adjacent-syllable
    swap ('메이플스토리' 오타 '메이플스퇴리/메이플스토리' 류) is 1 op — over
    the indexed Hangul vocabulary. Both paths only ever touch words the index
    has never seen, so correct queries are never rewritten.

    Replacements are collected as (start, end) spans over the ORIGINAL query
    and applied once, so a correction can never land inside a different word
    that merely shares a substring (an unbounded str.replace would rewrite
    the first occurrence anywhere, corrupting a longer indexed run)."""
    buckets = store.lexicon_buckets()
    repls: list[tuple[int, int, str]] = []

    for m in _ASCII_WORD_RE.finditer(query):
        word = m.group(0)
        lower = word.lower()
        if store.token_known(lower):
            continue
        cap = 1 if len(lower) <= 5 else 2
        best, best_key = None, (cap + 1, 0)
        # first-char bucket, not the full mixed vocabulary: on a Korean vault
        # the lexicon holds ~350k Hangul terms too, and a linear scan per
        # unknown ASCII word would walk all of them
        for term, doc_count in buckets.get(lower[0], ()):
            if abs(len(term) - len(lower)) > cap or not term[0].isascii():
                continue
            d = _edit_distance_capped(lower, term, cap)
            if d <= cap and (d, -doc_count) < (best_key[0], -best_key[1]):
                best, best_key = term, (d, doc_count)
        if best:
            repls.append((m.start(), m.end(), best))

    for m in _HANGUL_WORD_RE.finditer(query):
        word = m.group(0)
        if store.token_known(word):
            continue
        cap = 1 if len(word) <= 4 else 2
        best, best_key = None, (cap + 1, 0)
        # candidates: same first char (full cap), or same SECOND char for
        # first-syllable typos — those are single-character events, so the
        # wider bucket is held to distance 1 (letting it use the full cap
        # rewrote valid-but-unindexed words and cost KorQuAD precision)
        seen: set[str] = set()
        pools = [(buckets.get(word[0], ()), cap)]
        if len(word) >= 2:
            pools.append((buckets.get("\x02" + word[1], ()), 1))
        for pool, pool_cap in pools:
            for term, doc_count in pool:
                if term in seen:
                    continue
                seen.add(term)
                if abs(len(term) - len(word)) > pool_cap or not _HANGUL_RE.search(term):
                    continue
                d = _dl_distance_capped(word, term, pool_cap)
                if d <= pool_cap and (d, -doc_count) < (best_key[0], -best_key[1]):
                    best, best_key = term, (d, doc_count)
        if best and best != word:
            repls.append((m.start(), m.end(), best))

    if not repls:
        return query
    repls.sort()
    out: list[str] = []
    i = 0
    for start, end, replacement in repls:
        if start < i:  # overlapping span (shouldn't happen across disjoint
            continue    # char classes) — keep the earlier correction
        out.append(query[i:start])
        out.append(replacement)
        i = end
    out.append(query[i:])
    return "".join(out)


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

    # scoping operators (`tag:x folder:y ...`) restrict retrieval to a doc
    # subset. Parsed in every mode so `tag:회의록 예산` behaves the same in
    # vector/bm25 ablations as in hybrid.
    allowed_docs: set[int] | None = None
    clean, op_tags, op_folders = parse_operators(query)
    if op_tags or op_folders:
        allowed_docs = store.docs_matching(op_tags, op_folders)
        if not allowed_docs:
            return SearchResult(hits=[])
        query = clean
        if not query:
            # bare filter ("tag:회의록") = scoped listing, newest first
            return _filtered_listing(store, allowed_docs, k)

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
        # scoped queries over-fetch: the filter discards candidates, so the
        # legs must dig deeper to keep k results inside the scope
        depth = 4 if allowed_docs is not None else 1
        if mode in ("hybrid", "vector") and legs != "bm25":
            try:
                v = engine.embed_query_cached(q_text)
            except RuntimeError:
                # keyless: no embedding provider — the lexical leg carries the
                # search (BM25 + typo repair + boosts + operators still work)
                v = None
            if v is not None:
                if q_text == query:
                    qv = v
                v_hits = store.vector_search(v, cfg.k_vector * depth)
        if mode in ("hybrid", "bm25"):
            b_hits = store.bm25_search(q_text, cfg.k_bm25 * depth)
        if q_text == query:
            vec_hits, bm25_hits = v_hits, b_hits
        tagged_lists.append(("vec", v_hits, cfg.w_vector * weight))
        tagged_lists.append(("bm25", b_hits, cfg.w_bm25 * weight))

    # temporal intent is parsed once, up front: vague recency ("요즘/최근")
    # steers the verbatim-pin CHOICE below, not just the post-fusion boost —
    # "요즘 X는 뭐야?"의 답은 정의상 최신 언급이므로, 커버리지가 비슷한
    # 후보끼리는 최신 세션이 핀을 가져가야 한다 (RoleMemQA update-type:
    # 옛 선호를 축자로 되풀이하는 함정 세션이 핀을 훔치는 실패를 고침).
    rec_ctx = None
    now_ts = 0.0
    intent = None
    if mode == "hybrid" and cfg.recency_boost > 0:
        now_ts = getattr(engine, "now", time.time)()
        intent = parse_temporal(query, now=now_ts)
        if intent.active and intent.range_start is None:
            dates_all = store.doc_dates()
            if dates_all:
                # the memory's present = its newest note (never later than the
                # wall clock): archival/resumed vaults keep timeline order
                anchor = min(now_ts, max(dates_all.values()))
                rec_ctx = (dates_all, anchor, cfg.recency_half_life_days,
                           cfg.recency_boost)

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
        cov, cov_cid = 0.0, None
        bm25_damp = 1.0
        if kw_boost == 1.0 and bm25_hits:
            cov, cov_cid = _bm25_coverage(store, lex_query, bm25_hits, rec=rec_ctx,
                                          pin_gate=cfg.verbatim_pin_gate)
            if cov >= cfg.verbatim_gate:
                kw_boost = cfg.keyword_bm25_boost
            elif vec_hits and _all_tokens_common(store, lex_query):
                # every content token is corpus-boilerplate: the lexical
                # ranking is small-talk noise (measured on RoleMemQA chat
                # logs), so fusion leans on the semantic leg. Only when a
                # vector leg exists — keyless BM25-only installs unaffected.
                bm25_damp = cfg.common_bm25_damp
        fused = rrf_fuse(
            [(hits, w * ((kw_boost * bm25_damp) if kind == "bm25" else 1.0))
             for kind, hits, w in tagged_lists],
            cfg.rrf_k,
        )
        if cov >= cfg.verbatim_pin_gate and bm25_hits:
            # the query recites a note nearly token-for-token: BM25's own
            # ordering is authoritative, and rank-interleaved fusion can only
            # corrupt it (a chunk that is mediocre in BOTH legs outscores a
            # decisive lexical top-1 under RRF, because RRF sees ranks, not
            # margins). Keep every dense candidate — but strictly below the
            # lexical list, as gap-fillers.
            for r, (cid, _) in enumerate(bm25_hits[: cfg.verbatim_pin_head or None]):
                fused[cid] = 2.0 + 1.0 / (1 + r)
            # ...and the chunk that actually COVERS the query outranks even
            # that head: a masked-entity identifier often lives at BM25 rank
            # 4-8 (common tokens outscore it), yet it is the one chunk the
            # query is quoting — pin it first, wherever BM25 ranked it
            if cov_cid is not None:
                fused[cov_cid] = 3.5

    if not fused:
        return SearchResult(hits=[])

    chunk_meta = store.get_chunks(fused.keys())

    # --- recency: "요새 내가 하던 그거 뭐였지?" — when the query signals time
    # (vague recency or an explicit window), newer notes get boosted and notes
    # inside the asked window get boosted hardest. MULTIPLICATIVE on the fused
    # score, so recency amplifies relevance instead of replacing it: a fresh
    # but irrelevant note stays below an on-topic one. Rule-based, zero API.
    # vague recency ("요즘/최근") is measured from the MEMORY's present, not
    # the wall clock: in an archival or resumed vault (chat imports, roleplay
    # logs) every note is months old, so wall-clock decay flattens to ~0 for
    # all of them and an OLD stale fact ties a NEWER update. Anchoring at the
    # newest note keeps the timeline's internal order; a live vault (newest
    # note ≈ today) is unchanged. Explicit windows ("지난주", "5월에") stay
    # wall-clock — they name absolute time. Measured on RoleMemQA update-type.
    if mode == "hybrid" and intent is not None and intent.active:
        dates = rec_ctx[0] if rec_ctx else store.doc_dates()
        anchor = rec_ctx[1] if rec_ctx else now_ts
        doc_of = {cid: m.doc_id for cid, m in chunk_meta.items()}
        for cid in fused:  # values mutated in place; no keys added/removed
            ts = dates.get(doc_of.get(cid, -1), 0.0)
            if ts <= 0:
                continue
            if intent.range_start is not None:
                in_window = intent.range_start <= ts < (intent.range_end or now_ts)
                factor = 1.0 + cfg.recency_boost * (2.5 if in_window else 0.0)
            else:
                # gentler than the pin-choice weighting on purpose: the
                # corpus-wide multiplier rides on DIFFUSE relevance (every
                # session of a project matches its name), where a full-
                # strength 2x ceiling let brand-new small talk outrank a
                # 4-week-old decision whose relevance edge was 1.5x
                # (AgentMemQA decision-type). The PIN keeps full strength —
                # there recency chooses between candidates that all quote
                # the fact, which is exactly where it should be decisive.
                w = 0.6 * recency_weight(ts, anchor, cfg.recency_half_life_days)
                factor = 1.0 + cfg.recency_boost * w
            fused[cid] *= factor

    # --- title boost: a chunk from a note whose title matches query terms is
    # more likely the canonical source (Obsidian notes are entity-titled).
    # uses the typo-corrected text so a misspelled title still gets its boost
    q_tokens = _tokens(lex_query)
    if mode == "hybrid" and q_tokens and cfg.title_boost > 0:
        for cid, meta in chunk_meta.items():
            t_tokens = _tokens(meta.title)
            # date-stamped titles ("2023-09-12 Meeting with Steph" — the
            # Obsidian daily-note pattern) should match on their WORDS: the
            # numeric stamp tokens are never in a natural question, and
            # requiring them silently exempted every dated note from the
            # boost. Numeric tokens still help when the query has them.
            word_tokens = {t for t in t_tokens if not t.isdigit()}
            check = word_tokens or t_tokens
            if check and _covers(check, q_tokens):
                fused[cid] += cfg.title_boost * (len(check) / max(1, len(q_tokens)))

    # usage prior (opt-in, cfg.usage_prior=0 by default — see config.py for
    # why): multiplicative like recency, so it amplifies relevance only
    if mode == "hybrid" and cfg.usage_prior > 0:
        stats = store.hit_stats()
        if stats:
            import math

            mx = math.log1p(max(h for h, _ in stats.values()))
            if mx > 0:
                for cid, meta in chunk_meta.items():
                    s = stats.get(meta.doc_id)
                    if s and cid in fused:
                        fused[cid] *= 1.0 + cfg.usage_prior * math.log1p(s[0]) / mx

    expanded_docs: list[int] = []
    if use_graph and mode == "hybrid" and qv is not None:
        # lexical evidence for expansion: a neighbor chunk that already ranks
        # in the BM25 list is query-relevant no matter what the (possibly
        # weak) embedder thinks of it — carries "적정 레벨"-style residual
        # keywords to the linked doc that holds the answer
        bm25_rank = {cid: r for r, (cid, _) in enumerate(bm25_hits)}
        expanded_docs = _graph_expand(engine, fused, chunk_meta, qv, bm25_rank)
        new_ids = [cid for cid in fused if cid not in chunk_meta]
        if new_ids:  # only fetch what expansion added, not everything again
            chunk_meta.update(store.get_chunks(new_ids))

    # reranking: a dedicated cross-encoder reranker (Qwen3-Reranker) when
    # configured — purpose-built relevance judgment, unlike generic-LLM
    # self-scoring which a small model does badly. Falls back to the
    # generic LLM rerank when only `rerank` is set.
    use_reranker = cfg.reranker and mode == "hybrid"
    if use_reranker and fused:
        _dedicated_rerank(engine, query, fused, chunk_meta)
    elif use_rerank and fused:
        _llm_rerank(engine, query, fused, chunk_meta)

    if allowed_docs is not None:
        fused = {
            cid: s for cid, s in fused.items()
            if (m := chunk_meta.get(cid)) is not None and m.doc_id in allowed_docs
        }

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


def related_notes(engine: "Engine", path: str, k: int = 8) -> list[dict]:
    """reor-style related notes: the note itself is the query — zero LLM calls,
    zero embedding calls (its chunk vectors are already in the index).

    Score = best chunk-to-chunk cosine against the target note's centroid,
    with a small bonus for notes already link-connected to it (they're related
    by declaration, not just by wording)."""
    store = engine.store
    doc = store.get_doc_by_path(path)
    if doc is None:
        return []
    ids = store.doc_chunk_ids(doc.id)
    vecs = store.chunk_vectors(ids)
    if not vecs:
        return []
    import numpy as np

    centroid = np.mean(list(vecs.values()), axis=0)
    norm = np.linalg.norm(centroid)
    if norm < 1e-9:
        return []
    centroid /= norm

    linked = {n_id for n_id, _kind, _w in store.neighbors([doc.id]).get(doc.id, [])}
    cand = store.vector_search(centroid, max(48, k * 6))
    metas = store.get_chunks([cid for cid, _ in cand])  # one query, not N
    best: dict[int, float] = {}
    for cid, sim in cand:
        meta = metas.get(cid)
        if meta is None or meta.doc_id == doc.id:
            continue
        score = sim + (0.05 if meta.doc_id in linked else 0.0)
        if score > best.get(meta.doc_id, -1.0):
            best[meta.doc_id] = score

    docs = {d.id: d for d in store.all_docs()}
    out = []
    for did, score in sorted(best.items(), key=lambda x: -x[1])[:k]:
        d = docs.get(did)
        if d:
            out.append({"path": d.path, "title": d.title, "score": round(float(score), 4)})
    return out


def _filtered_listing(store: Store, allowed: set[int], k: int) -> SearchResult:
    """A bare scope filter with no residual query ('tag:회의록') lists the
    scope's notes newest-first — one representative chunk per note."""
    dates = store.doc_dates()
    hits: list[ChunkHit] = []
    for did in sorted(allowed, key=lambda d: -dates.get(d, 0.0))[:k]:
        ids = store.doc_chunk_ids(did)
        if not ids:
            continue
        meta = store.get_chunks([ids[0]])[ids[0]]
        meta.score = 0.0
        hits.append(meta)
    return SearchResult(hits=hits)


_QUESTION_WORDS = {
    "what", "which", "who", "when", "where", "why", "how", "did", "does", "do",
    "is", "are", "was", "were",
    "뭐", "뭔가", "무엇", "누구", "언제", "어디", "어디서", "어떻게", "왜", "몇",
}


_HANGUL_RE = re.compile(r"[가-힣]")

# Korean interrogatives — they never appear in note text, so counting them in
# coverage deflates the score of genuinely verbatim Korean questions
# ("~의 본명은 무엇인가?" quotes the note in every token but the last)
_KR_QWORD_PREFIXES = ("무엇", "뭐", "뭔", "무슨", "누구", "누가", "언제", "어디",
                      "어떻", "어떤", "어느", "얼마", "왜")

# Korean glue adverbs/deverbals that paraphrase freely between question and
# note ("함께 만든" vs "같이 만들었다") — noise for coverage, like _STOP
_KR_GLUE = {"함께", "같이", "위해", "위한", "대한", "대해", "있는", "있던",
            "되는", "이후", "당시", "때문"}


def _coverage_tokens(query: str) -> list[str]:
    toks = [t for t in _tokens(query)
            if not (_HANGUL_RE.search(t)
                    and (t.startswith(_KR_QWORD_PREFIXES) or t in _KR_GLUE))]
    # Korean questions name the ANSWER CATEGORY as their final topic-marked
    # noun — "~을 일으킨 인물은?", "~의 이름은?" — the Korean "who/what".
    # The note states the answer, not its category, so the focus word is
    # question furniture, not quotable content. Only for explicit questions:
    # in a declarative search ("프로젝트 예산은") the topic noun IS content.
    if query.rstrip().endswith("?"):
        words = query.rstrip().rstrip("?").split()
        if words:
            last_words = _WORD_RE.findall(words[-1].lower())
            if (last_words and _HANGUL_RE.search(last_words[-1])
                    and len(last_words[-1]) >= 2
                    and last_words[-1].endswith(("은", "는"))):
                toks = [t for t in toks if t != last_words[-1]]
    return toks


_JAMO_L = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JAMO_V = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JAMO_T = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ",
           "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ",
           "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]


def _to_jamo(s: str, drop_last_tail: bool = False) -> str:
    """Decompose Hangul syllables to jamo so conjugation survives matching:
    '만든' vs '만들었다' differ at the syllable level (ㄹ-drop) but share the
    jamo prefix ㅁㅏㄴㄷㅡ. Whitespace is dropped so 띄어쓰기 variation
    ('이루어져있는가' vs '이루어져 있다') can't break containment; other
    non-Hangul characters pass through."""
    out = []
    for i, ch in enumerate(s):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            code -= 0xAC00
            l, v, t = code // 588, (code % 588) // 28, code % 28
            out.append(_JAMO_L[l])
            out.append(_JAMO_V[v])
            if t and not (drop_last_tail and i == len(s) - 1):
                out.append(_JAMO_T[t])
        elif not ch.isspace():
            out.append(ch)
    return "".join(out)


def _token_in_text(t: str, text: str, text_jamo: str = "", stem: str = "") -> bool:
    if t in text:
        return True
    # agglutinative Hangul: the query token carries 조사/어미 the note won't
    # repeat ("본명은" vs "본명이") — accept a stem match, mirroring the
    # query-side suffix tolerance _covers() already gives titles
    if _HANGUL_RE.search(t):
        if len(t) >= 3 and t[:-1] in text:
            return True
        if len(t) >= 5 and t[:-2] in text:
            return True
        # conjugation-proof fallback: '만든'/'만들었다', '넣은'/'넣었다' — match
        # at the jamo level with the final consonant (받침) dropped, which is
        # where Korean verb endings mutate. `stem` is precomputed by the caller
        # (it depends only on the token, not the chunk) to avoid recomputing it
        # per (token x chunk).
        if text_jamo and len(t) >= 2:
            if not stem:
                stem = _to_jamo(t, drop_last_tail=True)
            if len(stem) >= 4 and stem in text_jamo:
                return True
    return False


# a term occurring more often than once per _COMMON_RATE chunks is corpus
# boilerplate: sits between measured "quoted term" rates (<0.03/chunk) and
# chat-filler rates (0.2+/chunk) with ~6x margin to each side
_COMMON_RATE = 0.05


def _all_tokens_common(store: Store, query: str) -> bool:
    """True when every content token of the query is corpus-boilerplate —
    present in more than _COMMON_RATE of all chunks (true chunk-level
    document frequency via FTS, so a rare entity repeated many times inside
    its one home note still counts as discriminative). Such a query carries
    no lexically discriminative evidence — its BM25 ranking is driven by
    repeated small talk (chat greetings/reactions), so verbatim machinery
    abstains and fusion leans on the semantic leg."""
    q_tokens = _coverage_tokens(query)
    if not q_tokens:
        return False
    n_chunks = max(1, store.chunk_count())
    # df floor: spread across at least _COMMON_RATE of chunks AND at least a
    # handful of distinct chunks — tiny vaults have no rate resolution
    floor = max(_COMMON_RATE * n_chunks, 4.0)

    def _df(t: str) -> int:
        df = store.token_chunk_df(t)
        if len(t) >= 3:  # 조사-glued surface: the stem's spread is what counts
            df = max(df, store.token_chunk_df(t[:-1]))
        return df

    return all(_df(t) > floor for t in q_tokens)


def _idf_weight(lex: dict, token: str) -> float:
    """Rarity weight for coverage: a quoted identifier ('문브릿지') should
    dominate the gate while question furniture ('보스', 'mp') barely counts.
    Uses the typo lexicon's surface-form counts; unseen surfaces (numbers,
    mixed-script runs the lexicon regex skips) are treated as rare — they
    are discriminative exactly because the vocabulary never saw them."""
    import math

    c = lex.get(token)
    if c is None and len(token) >= 3:
        c = lex.get(token[:-1])  # 조사-stripped surface ('문브릿지의'→'문브릿지')
    if c is None:
        c = 3
    return 1.0 / (1.0 + math.log1p(c))


def _bm25_coverage(store: Store, query: str,
                   bm25_hits: list[tuple[int, float]],
                   rec: tuple | None = None,
                   pin_gate: float = 0.65) -> tuple[float, int | None]:
    """(coverage, best_covering_chunk_id): the IDF-weighted fraction of the
    query's content tokens present in the best-covering top-8 BM25 chunk
    (title included), and that chunk's id.

    `rec` = (doc_dates, anchor_ts, half_life_days, boost) when the query has
    vague-recency intent ("요즘"): the returned COVERAGE stays pure (gates
    must not open on recency alone), but the CHOICE of best chunk is weighted
    by recency — among comparably-covering candidates the newest note wins,
    while a decisively better-covering old note still takes the pin.

    Count-based coverage under-fired on entity-masked questions: "위치가
    '문브릿지 : 공허의 눈'인 보스의 MP는?" quotes a unique identifier, but
    rare tokens were outvoted by unmatched common ones and the pin never
    fired — measured as hybrid 0.461 vs its own BM25 leg 0.735 on KorMapleQA
    masked. Weighting by rarity lets the identifier carry the gate while
    paraphrases (which avoid rare exact tokens by construction) stay below."""
    q_tokens = _coverage_tokens(query)
    # Hangul packs more content per token (조사 glue words instead of separate
    # prepositions, question furniture already stripped), so 2 Korean content
    # tokens carry what ~4+ English tokens do: "이충우의 본명은 무엇인가?"
    # leaves exactly {이충우의, 본명은} and IS a verbatim lookup
    has_hangul = any(_HANGUL_RE.search(t) for t in q_tokens)
    min_tokens = 2 if has_hangul else 4
    if len(q_tokens) < min_tokens:
        return 0.0, None
    # specificity gate: a genuine recitation quotes at least one term that is
    # discriminative in THIS corpus ("유노랑 한 약속이" is all-boilerplate →
    # abstain; see _all_tokens_common)
    if _all_tokens_common(store, query):
        return 0.0, None
    lex = store.lexicon()  # one cached-dict fetch, not one per token
    weights = {t: _idf_weight(lex, t) for t in q_tokens}
    total = sum(weights.values()) or 1.0
    # token stems depend only on the token, so precompute them once instead of
    # per (token x chunk) inside the loop below
    stems = {t: (_to_jamo(t, drop_last_tail=True)
                 if has_hangul and _HANGUL_RE.search(t) and len(t) >= 2 else "")
             for t in q_tokens}
    # top-8, not top-3: a masked-entity query's identifier often sits in the
    # rank-4..8 chunk (that being the problem the pin exists to fix) — a
    # 3-chunk window couldn't see the evidence that should open the gate
    meta = store.get_chunks([cid for cid, _ in bm25_hits[:8]])
    scored: list[tuple[float, float, int]] = []  # (cover, recency_weighted, cid)
    for cid, m in meta.items():
        text = (m.text + " " + m.title).lower()
        text_jamo = _to_jamo(text) if has_hangul else ""
        hit = sum(w for t, w in weights.items()
                  if _token_in_text(t, text, text_jamo, stems[t]))
        cover = hit / total
        weighted = cover
        if rec is not None:
            dates, anchor, hl, boost = rec
            ts = dates.get(m.doc_id, 0.0)
            if ts > 0:
                weighted = cover * (1.0 + boost * recency_weight(ts, anchor, hl))
        scored.append((cover, weighted, cid))
    if not scored:
        return 0.0, None
    best = max(c for c, _, _ in scored)
    # recency may only choose among AUTHORITATIVE candidates: anything at or
    # above the pin gate is, by the pin's own definition, verbatim enough to
    # be pinned — among those, the newest statement of the fact wins (a
    # superseded decision is often MORE verbatim than its paraphrased
    # correction: "캐시는 X로 가기로 했어" vs "뒤집는다, Y로 최종 확정" —
    # measured on AgentMemQA decision-type). A sub-gate chunk can never
    # steal the pin from a decisive verbatim match no matter how fresh
    # (review finding: 0.55-cover fresh vs 1.00-cover old).
    floor = min(0.8 * best, pin_gate)
    best_cid, best_w = None, 0.0
    for cover, weighted, cid in scored:  # first-wins on ties, like before
        if cover >= floor and weighted > best_w:
            best_w, best_cid = weighted, cid
    return best, best_cid


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


def _dedicated_rerank(
    engine: "Engine", query: str, fused: dict[int, float],
    chunk_meta: dict[int, ChunkHit]
) -> None:
    """Reorder the top candidates with a dedicated cross-encoder reranker.

    The in-process Qwen3-Reranker-0.6B (llama.cpp) returns a continuous
    relevance score P("yes") per candidate. We reorder the top `rerank_top`
    fused candidates by that score, all lifted above the fused range (best
    first), so the reranker only reorders what retrieval already surfaced —
    it never invents a ranking for chunks retrieval missed."""
    cfg = engine.cfg
    top = sorted(fused.items(), key=lambda x: -x[1])[: cfg.rerank_top]
    docs, cids = [], []
    for cid, _ in top:
        m = chunk_meta.get(cid)
        if m is None:
            continue
        cids.append(cid)
        # a cross-encoder's relevance signal lives in the title + lead; capping
        # the passage keeps that signal while bounding the reranker's prefill
        # cost (each candidate is a separate llama.cpp forward pass).
        docs.append((m.title + ". " + m.text)[:512])
    if not cids:
        return
    scores = _reranker_scores(engine, query, docs)
    if scores is None or len(scores) != len(cids):
        return  # keep fusion ranking on any reranker failure
    top_fused = max(fused.values(), default=1.0) or 1.0
    # cross-encoder continuous scores: reorder the candidates by relevance, all
    # lifted above the fused range (best first), so the reranker only reorders
    # what retrieval already surfaced
    order = sorted(range(len(cids)), key=lambda i: -scores[i])
    n = len(order)
    for rank, i in enumerate(order):
        fused[cids[i]] = top_fused + (n - rank)


def _reranker_scores(engine: "Engine", query: str, docs: list[str]) -> "list[float] | None":
    cfg = engine.cfg
    from ..providers import reranker
    try:
        return reranker.rerank_scores(query, docs, repo=cfg.reranker_gguf_repo,
                                      file=cfg.reranker_gguf_file)
    except Exception:
        return None


def _graph_expand(
    engine: "Engine",
    fused: dict[int, float],
    chunk_meta: dict[int, ChunkHit],
    qv,
    bm25_rank: dict[int, int] | None = None,
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

    # HippoRAG-style multi-hop propagation (bounded personalized-PageRank
    # walk): score mass flows outward from the seed notes along link edges,
    # decaying by graph_alpha per hop. graph_hops=1 is the classic 1-hop
    # expansion; 2 lets "A links B links C" carry evidence from A to C —
    # what real chains ("project → person → tool") need on real vaults.
    neighbor_gain: dict[int, float] = {}
    frontier = {src: doc_best[src] for src in top_docs}
    visited = set(top_docs)
    for _hop in range(max(1, cfg.graph_hops)):
        if not frontier:
            break
        all_nbrs = store.neighbors(list(frontier))
        nxt: dict[int, float] = {}
        for src, src_gain in frontier.items():
            nbrs = all_nbrs.get(src, [])
            # PPR-style degree normalization, hubs only: a note with dozens
            # of links diffuses its mass (measured on the obsidian-help vault:
            # unnormalized expansion floods top-k and LOSES to no-graph), while
            # curated personal linking (2-8 links) keeps full strength.
            norm = max(1.0, len(nbrs) / 8.0) ** 0.5
            for dst, _kind, w in nbrs:
                if dst == src:
                    continue
                g = cfg.graph_alpha * src_gain * w / norm
                # every dst may RECEIVE a boost — including another seed
                # (a weakly-fused gold note linked from the bridge is the
                # classic 2-hop case; excluding seeds broke it, measured)
                if g > neighbor_gain.get(dst, 0.0):
                    neighbor_gain[dst] = g
                # but the WALK only advances to unvisited notes (no cycles)
                if dst not in visited and g > nxt.get(dst, 0.0):
                    nxt[dst] = g
        visited |= set(nxt)
        frontier = nxt
    # workload ceiling before the (costly) chunk-similarity pass; the real
    # budget is applied AFTER sim-weighting so query relevance breaks ties —
    # link graphs have uniform edge weights, and cutting on gain alone would
    # drop gold neighbors arbitrarily. Neighbors holding a chunk that already
    # ranks in the BM25 list carry query keywords — they must survive the
    # ceiling ahead of gain-ties (a hub's 100+ equal-gain neighbors would
    # otherwise be cut in arbitrary insertion order).
    bm25_docs: set[int] = set()
    if bm25_rank:
        for cid in bm25_rank:
            m = chunk_meta.get(cid)
            if m is not None:
                bm25_docs.add(m.doc_id)
    if len(neighbor_gain) > 48:
        keep = sorted(neighbor_gain,
                      key=lambda d: (d not in bm25_docs, -neighbor_gain[d]))[:48]
        neighbor_gain = {d: neighbor_gain[d] for d in keep}

    chunk_ids_by_doc = store.doc_chunk_ids_many(list(neighbor_gain))
    all_sims = store.chunk_sims(qv, [c for ids in chunk_ids_by_doc.values() for c in ids])

    # expansion may fill ranks 2..k but must never displace the best direct
    # hit: multi-hop only needs the neighbor IN the top-k, while single-hop
    # precision depends on rank-1 staying with the direct evidence
    top_direct = max(fused.values(), default=0.0)
    cap = top_direct * 0.98

    # score every candidate by relevance-gated add, THEN apply the budget —
    # only the graph_expand_budget most query-relevant neighbors claim slots
    candidates = []
    for dst, gain in neighbor_gain.items():
        sims = {c: all_sims[c] for c in chunk_ids_by_doc.get(dst, []) if c in all_sims}
        if not sims:
            continue
        best_cid = max(sims, key=sims.get)
        sim = max(sims[best_cid], 0.0)
        # lexical relevance: best BM25 rank among this neighbor's chunks
        lex_rel = 0.0
        if bm25_rank:
            ranks = [bm25_rank[c] for c in chunk_ids_by_doc.get(dst, ())
                     if c in bm25_rank]
            if ranks:
                r = min(ranks)
                lex_rel = 1.0 - r / max(48, len(bm25_rank))
                # a lexically-matching chunk is the better boost target than
                # the (weak-embedder) cosine pick — redirect the boost to it
                if lex_rel >= sim:
                    best_cid = min((c for c in chunk_ids_by_doc.get(dst, ())
                                    if c in bm25_rank), key=bm25_rank.get)
        # relevance floor, applied to the STRONGER of the two signals: a
        # neighbor needs real cosine OR a real BM25 rank to clear it. A tail
        # hit at rank ~47 gives lex_rel ~0.02, which no longer sneaks a
        # semantically-unrelated linked note past the floor (single-hop safety)
        if max(sim, lex_rel) < cfg.graph_sim_floor:
            continue
        add = gain * (0.35 + 0.65 * max(sim, lex_rel))  # relevance-gated
        if add > 0:
            candidates.append((add, dst, best_cid, sims))

    expanded = []
    for add, dst, best_cid, sims in sorted(candidates, reverse=True)[: cfg.graph_expand_budget]:
        # a boost may never LOWER a chunk: a direct hit already scoring above
        # the cap must keep its own score (min() alone clamped it DOWN when
        # the neighbor's best chunk was itself a strong direct hit)
        cur = fused.get(best_cid, 0.0)
        fused[best_cid] = max(cur, min(cur + add, cap))
        # runner-up chunk at half strength (long notes may hold the fact deeper)
        rest = {c: s for c, s in sims.items() if c != best_cid}
        if rest:
            second = max(rest, key=rest.get)
            cur2 = fused.get(second, 0.0)
            fused[second] = max(cur2, min(cur2 + add * 0.5, cap))
        expanded.append(dst)
    return expanded
