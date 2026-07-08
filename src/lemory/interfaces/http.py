"""FastAPI server: point it at a vault and it keeps itself indexed.

    lemory serve --vault ~/Obsidian/MyVault

Endpoints:
    GET  /status
    POST /index          {"full": false}
    GET  /search?q=...&k=8&mode=hybrid
    POST /ask            {"question": "...", "k": 8}
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..engine import Engine

log = logging.getLogger("lemory.server")


class AskBody(BaseModel):
    question: str
    k: int = 8


class IndexBody(BaseModel):
    full: bool = False


def build_app(engine: Engine, watch: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine.index()
        if watch:
            def _watch():
                from ..ingestion import watch as _w
                try:
                    _w(engine)
                except Exception:
                    # a dead watcher means silently-stale search results —
                    # make the failure loud in the server log
                    log.exception(
                        "vault watcher crashed; the index will no longer "
                        "auto-update (POST /index still works)"
                    )
            threading.Thread(target=_watch, daemon=True, name="lemory-watcher").start()
        yield

    app = FastAPI(title="Lemory", version="0.1.0", lifespan=lifespan)

    # allow the Obsidian app (and local tools) to call this API directly
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["app://obsidian.md", "http://localhost", "http://127.0.0.1"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    def search(q: str, k: int = 8, mode: str = "hybrid",
               expand: bool | None = None, rerank: bool | None = None):
        if not q.strip():
            raise HTTPException(400, "empty query")
        hits = engine.search(q, k=k, mode=mode, expand=expand, rerank=rerank)
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
