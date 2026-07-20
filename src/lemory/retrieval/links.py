"""Link suggestions: turn the index's unlinked-mention edges into actionable
[[wikilink]] proposals · the "your notes are more connected than you wrote
down" half of a second brain.

The indexer already detects when note A's text mentions note B's title
without linking it (kind='mention' edges exist ONLY where no wiki edge does ·
see indexer._rebuild_links). This module surfaces those edges with the
sentence around the mention, so a human (or an agent with append rights) can
decide which ones deserve to become real links. Zero LLM, zero embeddings ·
it reads the graph the index already built.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import Engine

_SENT_SPLIT = re.compile(r"(?<=[.!?다요음됨])\s+|\n+")


def _mention_snippet(text: str, title: str, max_chars: int = 160) -> str:
    """First sentence of `text` containing `title` (case-insensitive)."""
    low_title = title.lower()
    for sent in _SENT_SPLIT.split(text):
        if low_title in sent.lower():
            s = sent.strip()
            return s[:max_chars] + ("…" if len(s) > max_chars else "")
    return ""


def suggest_links(engine: "Engine", path: str | None = None, k: int = 12) -> list[dict]:
    """Unlinked mentions as ranked [[link]] suggestions.

    With `path`: suggestions for that note (both directions · titles it
    mentions, and notes that mention it). Without: the vault's top unlinked
    mentions overall. Each row carries the mention's sentence so the decision
    can be made without opening the note."""
    store = engine.store
    docs = {d.id: d for d in store.all_docs()}

    src_filter = None
    if path is not None:
        doc = store.get_doc_by_path(path)
        if doc is None:
            raise ValueError(f"no such note: {path}")
        src_filter = doc.id

    rows = store.mention_edges(doc_id=src_filter)
    out = []
    chunk_cache: dict[int, str] = {}

    def doc_text(did: int) -> str:
        if did not in chunk_cache:
            ids = store.doc_chunk_ids(did)
            metas = store.get_chunks(ids)
            # body chunks only — enrichment pseudo-chunks quote other notes,
            # and a snippet must show where THIS note says the title
            chunk_cache[did] = "\n".join(
                metas[c].text for c in ids
                if c in metas and metas[c].heading != store.ENRICH_HEADING)
        return chunk_cache[did]

    for src, dst, weight in rows:
        s, d = docs.get(src), docs.get(dst)
        if s is None or d is None:
            continue
        snippet = _mention_snippet(doc_text(src), d.title)
        out.append({
            "from_path": s.path, "from_title": s.title,
            "to_path": d.path, "to_title": d.title,
            "weight": round(float(weight), 3),
            "snippet": snippet,
            "suggestion": f"[[{d.title}]]",
        })
    out.sort(key=lambda r: (-r["weight"], r["from_path"], r["to_title"]))
    return out[:k]
