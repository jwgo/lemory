"""Compact context: a fact sheet instead of raw chunk dumps.

Supermemory's headline result (LongMemEval, 95% Recall@15 while adding only
~720 tokens) comes from aggregating retrieved content into compact memories
before it reaches the model. Lemory's version is fully local and LLM-free:

  1. split each retrieved chunk into sentences (KR/EN aware),
  2. score sentences against the query with the SAME embedding cache the
     index uses (one batched call on first sight, free afterwards),
  3. keep the top sentences per chunk, rendered as dated one-liners.

The generator then sees "- [Note (2026-07-04)] fact…" lines · typically
5-10x fewer tokens than full chunks · with graceful fallback to the raw
chunk when a chunk has no scoreable sentences.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

from ..storage import ChunkHit

if TYPE_CHECKING:
    from ..engine import Engine

# sentence boundaries: ASCII terminators, Korean sentence endings, newlines
_SENT_SPLIT_RE = re.compile(
    r"(?<=[.!?])\s+|(?<=[다요죠음임함됨])\.\s*|\n+"
)


def split_sentences(text: str) -> list[str]:
    parts = [p.strip(" -•\t") for p in _SENT_SPLIT_RE.split(text)]
    # 8, not higher: Obsidian "Key facts" bullets are terse ("Lead: X") and
    # are exactly the lines that hold answers — over-filtering loses them
    return [p for p in parts if len(p) >= 8]


def build_compact_context(
    engine: "Engine",
    query: str,
    hits: list[ChunkHit],
    per_chunk: int = 3,
    max_chars: int = 4000,
) -> str:
    qv = engine.embed_query_cached(query)

    all_sents: list[tuple[int, str]] = []  # (hit index, sentence)
    for i, h in enumerate(hits):
        for s in split_sentences(h.text)[:30]:
            all_sents.append((i, s))
    if not all_sents:
        from .answer import build_context

        return build_context(hits, max_chars=max_chars)

    vecs, _ = engine.embed_documents_cached([s for _, s in all_sents])
    sims = vecs @ qv.astype(np.float32)

    by_hit: dict[int, list[tuple[float, str]]] = {}
    for (i, s), sim in zip(all_sents, sims):
        by_hit.setdefault(i, []).append((float(sim), s))

    lines: list[str] = []
    used = 0
    for i, h in enumerate(hits):
        scored = sorted(by_hit.get(i, []), reverse=True)[:per_chunk]
        if not scored:
            continue
        date_tag = ""
        if h.doc_date > 0:
            date_tag = f" ({datetime.fromtimestamp(h.doc_date).date().isoformat()})"
        # keep original chunk order of the selected sentences for readability
        chosen = [s for _, s in scored]
        chosen.sort(key=lambda s: h.text.find(s))
        body = " … ".join(chosen)
        line = f"[{i+1}] {h.title}{date_tag}: {body}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    if not lines:  # pathological: nothing survived — fall back to full chunks
        from .answer import build_context

        return build_context(hits, max_chars=max_chars)
    return "\n".join(lines)
