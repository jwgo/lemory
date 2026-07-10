"""ask(): retrieve, then answer with citations grounded in the vault."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..storage import ChunkHit

if TYPE_CHECKING:
    from ..engine import Engine

SYSTEM = (
    "You answer questions using ONLY the provided notes from the user's personal "
    "knowledge base. Cite sources inline as [n] using the note numbers given. "
    "Each note shows its date; when notes disagree, the most recent note states "
    "the current fact — prefer it and treat older notes as superseded. "
    "If the notes do not contain the answer, say you don't know — do not invent facts. "
    "Be direct and concise. Answer in the user's language."
)


@dataclass
class Answer:
    text: str
    sources: list[ChunkHit] = field(default_factory=list)

    def render_sources(self) -> str:
        lines = []
        for i, h in enumerate(self.sources, 1):
            lines.append(f"[{i}] {h.path}" + (f" › {h.heading}" if h.heading else ""))
        return "\n".join(lines)


def build_prompt(context: str, question: str, instruction: str = "ANSWER:") -> str:
    """The one prompt template for grounded answering — production ask() and
    the e2e benchmark must share it so benchmark numbers describe the real
    ask() path."""
    return f"NOTES:\n{context}\n\nQUESTION: {question}\n\n{instruction}"


def build_context(hits: list[ChunkHit], max_chars: int = 14000) -> str:
    from datetime import datetime

    parts = []
    used = 0
    for i, h in enumerate(hits, 1):
        date_tag = ""
        if h.doc_date > 0:
            date_tag = f" ({datetime.fromtimestamp(h.doc_date).date().isoformat()})"
        head = f"[{i}] {h.title}{date_tag}" + (f" › {h.heading}" if h.heading else "")
        body = h.text
        block = f"{head}\n{body}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


def answer(engine: "Engine", question: str, k: int = 8) -> Answer:
    from .intent import adaptive_k

    # list/count questions have evidence scattered across many notes — widen
    # retrieval so the generator sees every mention, not just the strongest
    k = adaptive_k(question, k, engine.cfg.adaptive_list_k)
    hits = engine.search(question, k=k)
    if not hits:
        return Answer(text="I couldn't find anything relevant in the vault.", sources=[])
    if engine.cfg.context_order == "curriculum":
        # CDS-inspired (arXiv:2605.13511): present evidence as a smooth
        # embedding-space trajectory instead of fusion-rank order — selection
        # is unchanged, only the reading order of the context. The query
        # vector is already cached from the search above.
        from .curriculum import curriculum_order

        try:
            qv = engine.embed_query_cached(question)
        except Exception:
            qv = None
        hits = curriculum_order(engine, qv, hits)
    if engine.cfg.context_style == "compact":
        from .compact import build_compact_context

        context = build_compact_context(engine, question, hits)
    else:
        context = build_context(hits)
    prompt = build_prompt(context, question)
    text = engine.llm.generate(prompt, system=SYSTEM, temperature=0.1)
    return Answer(text=text.strip(), sources=hits)
