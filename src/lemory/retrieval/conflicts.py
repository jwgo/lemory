"""Conflict scan: where does the vault disagree with itself?

Ported from Vestige's flagship idea (trust-weighted contradiction pairs) but
done Lemory-style: pure local math over the chunk matrix that already exists —
no LLM, no API, no extra storage. Two notes that say ALMOST the same thing
(high cosine) but differ on a concrete detail are exactly the pairs a human
wants surfaced:

- 'number'    — same claim, different figures ("가격은 $0.04" vs "$0.05")
- 'negation'  — one side negates what the other asserts
- 'duplicate' — near-identical content in two notes (dedup candidates)

High similarity is what makes the lexical signals meaningful: a number diff
between two UNRELATED chunks is noise, between two 0.85-cosine chunks it's a
disagreement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..storage import ChunkHit, Store

if TYPE_CHECKING:
    from ..engine import Engine

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
# dates are NOT numeric claims: two notes about the same topic written on
# different days would otherwise flag a fake "number conflict" on their date
# stamps (observed on real vaults: '(2026-07-15)' vs '예산 80만원'). Strip
# date-shaped tokens before extracting numbers; temporal ranking handles
# dates where they actually matter.
_DATE_RE = re.compile(
    r"\d{4}[-./년]\s?\d{1,2}[-./월]\s?\d{1,2}일?|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}년"
)
# tokens that flip a claim; substring match on purpose — Korean negation is
# agglutinated ('않는다', '없었다') and English contractions vary ("don't")
_NEG_TOKENS = ("않", "안 ", "없", "아니", "못 ", "금지", " not ", "n't", " no ", " never ")


@dataclass
class Conflict:
    a: ChunkHit
    b: ChunkHit
    similarity: float
    kind: str  # 'number' | 'negation' | 'duplicate'
    detail: str = ""


def _numbers(text: str) -> set[str]:
    text = _DATE_RE.sub(" ", text)
    return {m.group(0).replace(",", "") for m in _NUM_RE.finditer(text)}


def _has_negation(text: str) -> bool:
    padded = f" {text.lower()} "
    return any(t in padded for t in _NEG_TOKENS)


def _classify(a_text: str, b_text: str) -> tuple[str, str]:
    na, nb = _numbers(a_text), _numbers(b_text)
    if na and nb and na != nb:
        only_a, only_b = sorted(na - nb), sorted(nb - na)
        if only_a or only_b:
            return "number", f"{'/'.join(only_a) or '—'} vs {'/'.join(only_b) or '—'}"
    if _has_negation(a_text) != _has_negation(b_text):
        return "negation", "한쪽이 주장을 부정함"
    return "duplicate", "내용이 거의 동일함"


def find_conflicts(
    engine: "Engine",
    threshold: float = 0.80,
    limit: int = 30,
    kinds: tuple[str, ...] = ("number", "negation", "duplicate"),
) -> list[Conflict]:
    """Scan the whole vault for cross-note disagreements. Fully local."""
    store = engine.store
    pairs = store.similar_cross_doc_pairs(threshold, cap=limit * 20)
    if not pairs:
        return []
    meta = store.get_chunks({cid for p in pairs for cid in p[:2]})
    out: list[Conflict] = []
    seen_docs: set[tuple[int, int]] = set()
    for cid_a, cid_b, sim in pairs:
        a, b = meta.get(cid_a), meta.get(cid_b)
        if a is None or b is None:
            continue
        # enrichment pseudo-chunks (backlink context) mirror OTHER notes'
        # text by design — pairing them reports the mirror, not a conflict
        if Store.ENRICH_HEADING in (a.heading, b.heading):
            continue
        key = (min(a.doc_id, b.doc_id), max(a.doc_id, b.doc_id))
        if key in seen_docs:  # one finding per note pair keeps the report readable
            continue
        kind, detail = _classify(a.text, b.text)
        if kind not in kinds:
            continue
        seen_docs.add(key)
        out.append(Conflict(a=a, b=b, similarity=sim, kind=kind, detail=detail))
        if len(out) >= limit:
            break
    # contradictions before duplicates: they're the actionable ones
    priority = {"number": 0, "negation": 1, "duplicate": 2}
    out.sort(key=lambda c: (priority[c.kind], -c.similarity))
    return out
