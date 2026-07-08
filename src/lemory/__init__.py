"""Lemory — a high-performance personal knowledge base for your Obsidian vault.

Quickstart (cognee-style):

    import lemory

    lemory.configure(vault="~/Obsidian/MyVault")   # or set LEMORY_VAULT / lemory.toml
    lemory.index()                                  # incremental; safe to re-run
    hits = lemory.search("what did I decide about the pricing model?")
    print(lemory.ask("what did I decide about the pricing model?").text)
"""

from __future__ import annotations

from typing import Optional

from .retrieval import Answer
from .config import LemoryConfig, load_config
from .engine import Engine, create_engine
from .storage import ChunkHit

__version__ = "0.1.0"
__all__ = [
    "configure", "index", "watch", "search", "ask", "status", "reset",
    "Engine", "LemoryConfig", "ChunkHit", "Answer", "create_engine",
]

_engine: Optional[Engine] = None


def configure(**kwargs) -> Engine:
    """Configure the global Lemory engine. Accepts any LemoryConfig field."""
    global _engine
    if _engine is not None:
        _engine.close()
    _engine = Engine(load_config(**kwargs))
    return _engine


def _get() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine(load_config())
    return _engine


def index(full: bool = False):
    """Incrementally index the vault (only changed notes are re-embedded)."""
    return _get().index(full=full)


def watch() -> None:
    """Index, then block and keep the index live as the vault changes."""
    _get().watch()


def search(query: str, k: int = 8, **kw) -> list[ChunkHit]:
    return _get().search(query, k=k, **kw)


def ask(question: str, k: int = 8) -> Answer:
    return _get().ask(question, k=k)


def status() -> dict:
    return _get().status()


def reset() -> None:
    """Drop the global engine (mainly for tests)."""
    global _engine
    if _engine is not None:
        _engine.close()
    _engine = None
