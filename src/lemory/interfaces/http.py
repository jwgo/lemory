"""FastAPI server: point it at a vault and it keeps itself indexed.

    lemory serve --vault ~/Obsidian/MyVault

Public API:
    GET  /status
    POST /index          {"full": false}
    GET  /search?q=...&k=8&mode=hybrid
    POST /ask            {"question": "...", "k": 8}

Console API (backs the web UI at /):
    GET   /api/overview      stats, models, storage, watcher, recent activity
    GET   /api/notes         per-note rows for the knowledge explorer
    GET   /api/note?path=    full note detail: chunks, links in/out, tags
    GET   /api/tags          tag histogram
    GET   /api/config        runtime-tunable settings
    PATCH /api/config        update settings (persisted to <vault>/lemory.toml)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from ..engine import Engine

log = logging.getLogger("lemory.server")

# settings the console may read AND write. Everything else is visible via
# /status or requires a restart (models, vault path) — keeping the writable
# surface small makes PATCH safe.
TUNABLE_FIELDS: dict[str, type] = {
    "graph_expansion": bool,
    "mention_links": bool,
    "typo_correction": bool,
    "query_expansion": bool,
    "rerank": bool,
    "enrich_entities": bool,
    "context_style": str,       # "full" | "compact"
    "context_order": str,       # "curriculum" | "rank"
    "title_boost": float,
    "recency_boost": float,
    "recency_half_life_days": float,
    "graph_alpha": float,
    "graph_sim_floor": float,
    "per_doc_cap": int,
    "k_vector": int,
    "k_bm25": int,
    "chunk_chars": int,
    "chunk_overlap": int,
}

ACTIVITY_KEY = "console_activity"
ACTIVITY_MAX = 60


class AskBody(BaseModel):
    question: str
    k: int = 8


class IndexBody(BaseModel):
    full: bool = False


class MemoryBody(BaseModel):
    content: str
    title: str = ""
    folder: str = "memories"
    tags: list[str] = []


class AppendBody(BaseModel):
    path: str
    content: str


def _console_file(name: str) -> Path:
    return Path(str(resources.files("lemory.interfaces").joinpath("console", name)))


def _log_activity(engine: Engine, kind: str, rep) -> None:
    """Append a sync report to the ring buffer shown on the console overview."""
    try:
        raw = engine.store.get_meta(ACTIVITY_KEY)
        items = json.loads(raw) if raw else []
        items.append({
            "ts": time.time(), "kind": kind,
            "added": rep.added, "updated": rep.updated, "removed": rep.removed,
            "chunks": rep.chunks, "embedded": rep.embedded,
            "seconds": round(rep.seconds, 2),
        })
        engine.store.set_meta(ACTIVITY_KEY, json.dumps(items[-ACTIVITY_MAX:]))
    except Exception:  # activity log must never break indexing
        log.exception("failed to record activity")


def build_app(engine: Engine, watch: bool = True) -> FastAPI:
    state = {"watcher_alive": False, "started_at": time.time()}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        rep = engine.index()
        _log_activity(engine, "startup", rep)
        if watch:
            def _watch():
                from ..ingestion import watch as _w
                state["watcher_alive"] = True
                try:
                    _w(engine, on_sync=lambda r: _log_activity(engine, "watch", r)
                       if r.changed else None)
                except Exception:
                    # a dead watcher means silently-stale search results —
                    # make the failure loud in the server log
                    log.exception(
                        "vault watcher crashed; the index will no longer "
                        "auto-update (POST /index still works)"
                    )
                finally:
                    state["watcher_alive"] = False
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

    # ------------------------------------------------------------ console UI
    @app.get("/", include_in_schema=False)
    def home():
        return HTMLResponse(_console_file("index.html").read_text(encoding="utf-8"))

    @app.get("/assets/{name}", include_in_schema=False)
    def assets(name: str):
        if name not in ("app.css", "app.js"):
            raise HTTPException(404)
        media = "text/css" if name.endswith(".css") else "text/javascript"
        return FileResponse(_console_file(name), media_type=media)

    # ------------------------------------------------------------ public API
    @app.get("/status")
    def status():
        return engine.status()

    @app.post("/index")
    def index(body: IndexBody):
        rep = engine.index(full=body.full)
        _log_activity(engine, "manual", rep)
        return {
            "added": rep.added, "updated": rep.updated, "removed": rep.removed,
            "unchanged": rep.unchanged, "chunks": rep.chunks,
            "embedded": rep.embedded, "seconds": rep.seconds,
        }

    @app.get("/search")
    def search(q: str, k: int = 8, mode: str = "hybrid",
               graph: bool | None = None,
               expand: bool | None = None, rerank: bool | None = None):
        if not q.strip():
            raise HTTPException(400, "empty query")
        hits = engine.search(q, k=k, mode=mode, graph=graph, expand=expand, rerank=rerank, record=True)
        return [_hit_json(h, text=True) for h in hits]

    @app.post("/ask")
    def ask(body: AskBody):
        ans = engine.ask(body.question, k=body.k, record=True)
        return {
            "answer": ans.text,
            "sources": [_hit_json(h, text=True) for h in ans.sources],
        }

    @app.get("/context")
    def context(max_chars: int = 2400):
        """Pre-assembled vault context (Zep-style): stats, recent activity,
        frequently referenced notes, hubs, tags — one cheap local call."""
        from ..ingestion.memory import context_block

        return {"context": context_block(engine, max_chars=max_chars)}

    @app.post("/memory")
    def memory(body: MemoryBody):
        """Write path: persist a memory as a new Markdown note in the vault."""
        from ..ingestion.memory import save_memory

        try:
            path = save_memory(engine, body.content, title=body.title,
                               folder=body.folder, tags=body.tags)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"saved": path}

    @app.post("/append")
    def append(body: AppendBody):
        """Append-only write to an existing note (creates it if missing)."""
        from ..ingestion.memory import append_to_note

        try:
            rel = append_to_note(engine, body.path, body.content)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"appended": rel}

    # ----------------------------------------------------------- console API
    @app.get("/api/overview")
    def overview():
        st = engine.status()
        db_bytes = engine.store.db_path.stat().st_size if engine.store.db_path.exists() else 0
        raw = engine.store.get_meta(ACTIVITY_KEY)
        activity = list(reversed(json.loads(raw)))[:20] if raw else []
        cfg = engine.cfg
        return {
            **st,
            "tags": len(engine.store.tag_counts()),
            "cached_embeddings": engine.store.embed_cache_count(),
            "db_bytes": db_bytes,
            "watcher_alive": state["watcher_alive"],
            "uptime_s": round(time.time() - state["started_at"]),
            "provider": _safe(cfg.resolved_provider) if hasattr(cfg, "resolved_provider") else None,
            "graph_expansion": cfg.graph_expansion,
            "activity": activity,
        }

    @app.get("/api/index_plan")
    def index_plan(full: bool = False):
        p = engine.index_plan(full=full)
        return {
            "files_total": p.files_total, "to_process": p.to_process,
            "to_remove": p.to_remove, "chunks_total": p.chunks_total,
            "embeds_needed": p.embeds_needed,
            "est_seconds": round(p.est_seconds, 1), "eta": p.human_eta(),
            "rate_chunks_per_s": round(p.rate_chunks_per_s, 1),
            "rate_measured": p.rate_measured,
        }

    @app.get("/api/notes")
    def notes():
        return engine.store.doc_overview_rows()

    @app.get("/api/note")
    def note(path: str):
        d = engine.store.doc_detail(path)
        if d is None:
            raise HTTPException(404, f"note not found: {path}")
        return d

    @app.get("/api/tags")
    def tags():
        return engine.store.tag_counts()

    @app.get("/api/config")
    def get_config():
        cfg = engine.cfg
        values = {k: getattr(cfg, k) for k in TUNABLE_FIELDS}
        readonly = {
            "vault": str(cfg.vault) if cfg.vault else None,
            "provider": _safe(cfg.resolved_provider) if hasattr(cfg, "resolved_provider") else None,
            "llm_model": _safe(cfg.active_llm_model) if hasattr(cfg, "active_llm_model") else cfg.llm_model,
            "embed_model": _safe(cfg.active_embed_model) if hasattr(cfg, "active_embed_model") else cfg.embed_model,
            "embed_dim": _safe(cfg.active_embed_dim) if hasattr(cfg, "active_embed_dim") else cfg.embed_dim,
        }
        return {"tunable": values, "readonly": readonly}

    @app.patch("/api/config")
    def patch_config(body: dict[str, Any]):
        changed: dict[str, Any] = {}
        for key, value in body.items():
            if key not in TUNABLE_FIELDS:
                raise HTTPException(400, f"not a tunable setting: {key}")
            typ = TUNABLE_FIELDS[key]
            try:
                if typ is bool:
                    coerced = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on")
                else:
                    coerced = typ(value)
            except (TypeError, ValueError):
                raise HTTPException(400, f"bad value for {key}: {value!r}")
            if key == "context_style" and coerced not in ("full", "compact"):
                raise HTTPException(400, "context_style must be 'full' or 'compact'")
            if key == "context_order" and coerced not in ("curriculum", "rank"):
                raise HTTPException(400, "context_order must be 'curriculum' or 'rank'")
            setattr(engine.cfg, key, coerced)
            changed[key] = coerced
        if changed:
            _persist_config(engine, changed)
        return {"changed": changed}

    return app


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _persist_config(engine: Engine, changed: dict[str, Any]) -> None:
    """Merge changed keys into <vault>/lemory.toml so they survive restarts."""
    try:
        vault = engine.cfg.resolved_vault()
    except RuntimeError:
        return
    path = vault / "lemory.toml"
    existing: dict[str, Any] = {}
    if path.is_file():
        import tomllib
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
            existing = data.get("lemory", data)
        except tomllib.TOMLDecodeError:
            log.warning("could not parse %s; not persisting settings", path)
            return
    existing.update(changed)
    # the file must stay self-sufficient: without the vault key, running the
    # CLI next to this toml would lose track of which vault it belongs to
    existing.setdefault("vault", str(vault))
    lines = ["[lemory]"]
    for k, v in existing.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{v}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hit_json(h, text: bool = False) -> dict:
    from datetime import datetime

    out = {
        "path": h.path, "title": h.title, "heading": h.heading, "score": h.score,
        "date": datetime.fromtimestamp(h.doc_date).date().isoformat() if h.doc_date > 0 else None,
    }
    if text:
        out["text"] = h.text
    return out
