"""ask(): retrieve, then answer with citations grounded in the vault."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .store import ChunkHit

if TYPE_CHECKING:
    from .engine import Engine

SYSTEM = (
    "You answer questions using ONLY the provided notes from the user's personal "
    "knowledge base. Cite sources inline as [n] using the note numbers given. "
    "If the notes do not contain the answer, say you don't know — do not invent facts. "
    "Be direct and concise."
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


def build_context(hits: list[ChunkHit], max_chars: int = 14000) -> str:
    parts = []
    used = 0
    for i, h in enumerate(hits, 1):
        head = f"[{i}] {h.title}" + (f" › {h.heading}" if h.heading else "")
        body = h.text
        block = f"{head}\n{body}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


def answer(engine: "Engine", question: str, k: int = 8) -> Answer:
    hits = engine.search(question, k=k)
    if not hits:
        return Answer(text="I couldn't find anything relevant in the vault.", sources=[])
    context = build_context(hits)
    prompt = f"NOTES:\n{context}\n\nQUESTION: {question}\n\nANSWER:"
    text = engine.llm.generate(prompt, system=SYSTEM, temperature=0.1)
    return Answer(text=text.strip(), sources=hits)
