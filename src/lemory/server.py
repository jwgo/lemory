"""FastAPI server: point it at a vault and it keeps itself indexed.

    lemory serve --vault ~/Obsidian/MyVault

Endpoints:
    GET  /status
    POST /index          {"full": false}
    GET  /search?q=...&k=8&mode=hybrid
    POST /ask            {"question": "...", "k": 8}
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .engine import Engine


class AskBody(BaseModel):
    question: str
    k: int = 8


class IndexBody(BaseModel):
    full: bool = False


def build_app(engine: Engine, watch: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine.index()
        stop = threading.Event()
        t = None
        if watch:
            def _watch():
                from .ingest import watch as _w
                try:
                    _w(engine)
                except Exception:
                    pass
            t = threading.Thread(target=_watch, daemon=True)
            t.start()
        yield
        stop.set()

    app = FastAPI(title="Lemory", version="0.1.0", lifespan=lifespan)

    @app.get("/status")
    def status():
        return engine.status()

    @app.post("/index")
    def index(body: IndexBody):
        rep = engine.index(full=body.full)
        return {
            "added": rep.added, "updated": rep.updated, "removed": rep.removed,
            "unchanged": rep.unchanged, "chunks": rep.chunks,
            "embedded": rep.embedded, "seconds": rep.seconds,
        }

    @app.get("/search")
    def search(q: str, k: int = 8, mode: str = "hybrid"):
        if not q.strip():
            raise HTTPException(400, "empty query")
        hits = engine.search(q, k=k, mode=mode)
        return [
            {
                "path": h.path, "title": h.title, "heading": h.heading,
                "text": h.text, "score": h.score,
            }
            for h in hits
        ]

    @app.post("/ask")
    def ask(body: AskBody):
        ans = engine.ask(body.question, k=body.k)
        return {
            "answer": ans.text,
            "sources": [
                {"path": h.path, "title": h.title, "heading": h.heading, "score": h.score}
                for h in ans.sources
            ],
        }

    return app
