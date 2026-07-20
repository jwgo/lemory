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
    "the current fact · prefer it and treat older notes as superseded. "
    "If the notes do not contain the answer, say you don't know · do not invent facts. "
    "Be direct and concise. Answer in the user's language."
)


@dataclass
class Answer:
    text: str
    sources: list[ChunkHit] = field(default_factory=list)

    def render_sources(self) -> str:
        lines = []
        for i, h in enumerate(self.sources, 1):
            sub = h.subheading()
            lines.append(f"[{i}] {h.path}" + (f" › {sub}" if sub else ""))
        return "\n".join(lines)


def build_prompt(context: str, question: str, instruction: str = "ANSWER:") -> str:
    """The one prompt template for grounded answering · production ask() and
    the e2e benchmark must share it so benchmark numbers describe the real
    ask() path."""
    return f"NOTES:\n{context}\n\nQUESTION: {question}\n\n{instruction}"


def build_context(hits: list[ChunkHit], max_chars: int = 14000,
                  store=None, neighbor_chars: int = 0) -> str:
    """Numbered evidence blocks for the generator. With `store` and
    neighbor_chars > 0, each block is expanded with the tail of the previous
    chunk and the head of the next (Cerebras-style post-ranking expansion):
    ranking already decided WHAT to read; this restores the preconditions and
    caveats the chunk boundary cut away. Selection is unchanged."""
    from datetime import datetime

    parts = []
    used = 0
    for i, h in enumerate(hits, 1):
        date_tag = ""
        if h.doc_date > 0:
            date_tag = f" ({datetime.fromtimestamp(h.doc_date).date().isoformat()})"
        head = f"[{i}] {h.title}{date_tag}" + (f" › {h.heading}" if h.heading else "")
        body = h.text
        if store is not None and neighbor_chars > 0:
            prev_t, next_t = store.adjacent_chunks(h.chunk_id)
            if prev_t:
                body = f"…{prev_t[-neighbor_chars:]}\n{body}"
            if next_t:
                body = f"{body}\n{next_t[:neighbor_chars]}…"
        block = f"{head}\n{body}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


def _decompose(engine: "Engine", question: str, n: int = 3) -> list[str]:
    """Deep mode: LLM splits a hard question into the sub-facts it needs.
    One call; failures degrade to no decomposition."""
    try:
        data = engine.llm.generate_json(
            "Break this question about a personal notes vault into up to "
            f"{n} independent sub-questions, each asking for ONE fact needed "
            'to answer it. Return JSON: {"queries": ["..."]}\n\n'
            f"QUESTION: {question}",
            temperature=0.2, max_output_tokens=256,
        )
        subs = [q.strip() for q in data.get("queries", []) if isinstance(q, str)]
        return [q for q in subs if q and q.lower() != question.lower()][:n]
    except Exception:
        return []


def answer(engine: "Engine", question: str, k: int = 8, deep: bool = False) -> Answer:
    from .intent import adaptive_k

    # list/count questions have evidence scattered across many notes — widen
    # retrieval so the generator sees every mention, not just the strongest
    k = adaptive_k(question, k, engine.cfg.adaptive_list_k)
    hits = engine.search(question, k=k)
    if deep:
        # agentic round: retrieve each sub-question separately and merge —
        # multi-fact questions whose facts never co-occur in one chunk get
        # every leg of their evidence into the context. Costs one LLM call
        # plus a few lexical/vector searches; opt-in (`lemory ask --deep`).
        seen = {h.chunk_id for h in hits}
        for sub in _decompose(engine, question):
            for h in engine.search(sub, k=max(3, k // 2)):
                if h.chunk_id not in seen:
                    seen.add(h.chunk_id)
                    hits.append(h)
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
        context = build_context(
            hits, store=engine.store,
            neighbor_chars=engine.cfg.context_neighbor_chars
            if engine.cfg.context_neighbors else 0)
    prompt = build_prompt(context, question)
    text = engine.llm.generate(prompt, system=SYSTEM, temperature=0.1)
    return Answer(text=text.strip(), sources=hits)
