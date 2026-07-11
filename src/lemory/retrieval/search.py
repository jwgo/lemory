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
    has never seen, so correct queries are never rewritten."""
    lexicon = None
    corrected = query

    def _lex():
        nonlocal lexicon
        if lexicon is None:
            lexicon = store.lexicon()
        return lexicon

    for m in _ASCII_WORD_RE.finditer(query):
        word = m.group(0)
        lower = word.lower()
        if store.token_known(lower):
            continue
        cap = 1 if len(lower) <= 5 else 2
        best, best_key = None, (cap + 1, 0)
        for term, doc_count in _lex().items():
            if term[0] != lower[0] or abs(len(term) - len(lower)) > cap:
                continue
            d = _edit_distance_capped(lower, term, cap)
            if d <= cap and (d, -doc_count) < (best_key[0], -best_key[1]):
                best, best_key = term, (d, doc_count)
        if best:
            corrected = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", best, corrected)

    for m in _HANGUL_WORD_RE.finditer(query):
        word = m.group(0)
        if store.token_known(word):
            continue
        cap = 1 if len(word) <= 4 else 2
        best, best_key = None, (cap + 1, 0)
        # first-syllable bucket + length filter: O(bucket), not O(vocab)
        for term, doc_count in store.lexicon_buckets().get(word[0], ()):
            if abs(len(term) - len(word)) > cap or not _HANGUL_RE.search(term):
                continue
            d = _dl_distance_capped(word, term, cap)
            if d <= cap and (d, -doc_count) < (best_key[0], -best_key[1]):
                best, best_key = term, (d, doc_count)
        if best and best != word:
            corrected = corrected.replace(word, best, 1)
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
        cov = 0.0
        if kw_boost == 1.0 and bm25_hits:
            cov = _bm25_coverage(store, lex_query, bm25_hits)
            if cov >= cfg.verbatim_gate:
                kw_boost = cfg.keyword_bm25_boost
        fused = rrf_fuse(
            [(hits, w * (kw_boost if kind == "bm25" else 1.0))
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
            for cid in fused:  # values mutated in place; no keys added/removed
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
        expanded_docs = _graph_expand(engine, fused, chunk_meta, qv)
        new_ids = [cid for cid in fused if cid not in chunk_meta]
        if new_ids:  # only fetch what expansion added, not everything again
            chunk_meta.update(store.get_chunks(new_ids))

    # qmd-style LLM rerank: score the top candidates for relevance and blend
    # with the fusion score (costs one LLM call per search)
    if use_rerank and fused:
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


def _token_in_text(t: str, text: str, text_jamo: str = "") -> bool:
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
        # where Korean verb endings mutate
        if text_jamo and len(t) >= 2:
            stem = _to_jamo(t, drop_last_tail=True)
            if len(stem) >= 4 and stem in text_jamo:
                return True
    return False


def _bm25_coverage(store: Store, query: str, bm25_hits: list[tuple[int, float]]) -> float:
    """Fraction of the query's content tokens present in the best-covering
    top-3 BM25 chunk (title included)."""
    q_tokens = _coverage_tokens(query)
    # Hangul packs more content per token (조사 glue words instead of separate
    # prepositions, question furniture already stripped), so 2 Korean content
    # tokens carry what ~4+ English tokens do: "이충우의 본명은 무엇인가?"
    # leaves exactly {이충우의, 본명은} and IS a verbatim lookup
    has_hangul = any(_HANGUL_RE.search(t) for t in q_tokens)
    min_tokens = 2 if has_hangul else 4
    if len(q_tokens) < min_tokens:
        return 0.0
    meta = store.get_chunks([cid for cid, _ in bm25_hits[:3]])
    best = 0.0
    for m in meta.values():
        text = (m.text + " " + m.title).lower()
        text_jamo = _to_jamo(text) if has_hangul else ""
        hit = sum(1 for t in q_tokens if _token_in_text(t, text, text_jamo))
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
    # drop gold neighbors arbitrarily
    if len(neighbor_gain) > 48:
        keep = sorted(neighbor_gain, key=lambda d: -neighbor_gain[d])[:48]
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
        if sim < cfg.graph_sim_floor:
            # neighbor's content has nothing to do with the query: linked-but-
            # irrelevant notes must not displace direct hits (single-hop safety)
            continue
        add = gain * (0.35 + 0.65 * sim)  # relevance-gated: irrelevant neighbors decay
        if add > 0:
            candidates.append((add, dst, best_cid, sims))

    expanded = []
    for add, dst, best_cid, sims in sorted(candidates, reverse=True)[: cfg.graph_expand_budget]:
        fused[best_cid] = min(fused.get(best_cid, 0.0) + add, cap)
        # runner-up chunk at half strength (long notes may hold the fact deeper)
        rest = {c: s for c, s in sims.items() if c != best_cid}
        if rest:
            second = max(rest, key=rest.get)
            fused[second] = min(fused.get(second, 0.0) + add * 0.5, cap)
        expanded.append(dst)
    return expanded
