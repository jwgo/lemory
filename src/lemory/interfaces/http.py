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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..engine import Engine

log = logging.getLogger("lemory.server")

# settings the console may read AND write. Everything else is visible via
# /status or requires a restart (models, vault path) — keeping the writable
# surface small makes PATCH safe.
TUNABLE_FIELDS: dict[str, type] = {
    # embedding backend selection. Unlike the live knobs below, changing these
    # only takes effect on the next start and needs a full re-index (the vector
    # space changes); the UI labels them accordingly and persists to lemory.toml.
    "provider": str,             # auto | gemini | openai | local
    "local_embed_backend": str,  # auto | llamacpp | fastembed
    "event_log": bool,
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


class ChatBody(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": str}, ...]


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


class TrashBody(BaseModel):
    path: str


def _client(request: "Request") -> str:
    """Client attribution for the middleware timeline. Callers self-identify
    with the X-Lemory-Client header (the Obsidian plugin, scripts, agents);
    anonymous callers show up as plain 'http'."""
    return (request.headers.get("x-lemory-client") or "http").strip()[:40]


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

    # DNS-rebinding defense. This server has no auth and exposes write/delete
    # endpoints (/memory, /append, /memory/trash, /index). It binds 127.0.0.1,
    # but a malicious web page can rebind its own hostname to 127.0.0.1 and
    # POST to it from the victim's browser — CORS doesn't stop that, because
    # after rebinding the request is same-origin. The rebound request still
    # carries the attacker's Host header, so a hostname allowlist blocks it
    # while letting real localhost clients (browser console, Obsidian) through.
    from starlette.responses import PlainTextResponse

    _ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", ""}

    @app.middleware("http")
    async def _host_guard(request, call_next):
        host = request.headers.get("host", "")
        # strip port: "127.0.0.1:8377" -> "127.0.0.1", "[::1]:8377" -> "::1"
        hostname = host.rsplit(":", 1)[0] if ":" in host and not host.endswith("]") \
            else host
        hostname = hostname.strip("[]")
        if hostname not in _ALLOWED_HOSTS:
            return PlainTextResponse(
                "host not allowed (DNS-rebinding guard)", status_code=421)
        return await call_next(request)

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
    def search(request: Request, q: str, k: int = 8, mode: str = "hybrid",
               graph: bool | None = None,
               expand: bool | None = None, rerank: bool | None = None):
        if not q.strip():
            raise HTTPException(400, "empty query")
        hits = engine.search(q, k=k, mode=mode, graph=graph, expand=expand,
                             rerank=rerank, record=True, client=_client(request))
        return [_hit_json(h, text=True) for h in hits]

    @app.post("/ask")
    def ask(request: Request, body: AskBody):
        ans = engine.ask(body.question, k=body.k, record=True, client=_client(request))
        return {
            "answer": ans.text,
            "sources": [_hit_json(h, text=True) for h in ans.sources],
        }

    # ------------------------------------------------- assistant (console chat)
    @app.get("/api/assistant/status")
    def assistant_status():
        """Is the on-device assistant brain ready? Default is Gemma 4 E4B on
        llama.cpp (Q4_K_M GGUF); the console gates 'assistant mode' on this."""
        cfg = engine.cfg
        from ..providers import gemma, supertonic_tts, whisper_stt
        ok, reason = gemma.available()
        size = next((k for k, (r, f) in gemma.MODELS.items()
                     if f == cfg.assistant_gguf_file), "E4B")
        return {"available": ok, "model": cfg.assistant_gguf_file, "reason": reason,
                "size": size, "sizes": list(gemma.MODELS),
                "voices": list(supertonic_tts.VOICES), "tts_voice": cfg.assistant_tts_voice,
                "tts": supertonic_tts.available()[0], "stt": whisper_stt.available()[0]}

    @app.post("/api/assistant/model")
    def assistant_model(body: dict[str, Any]):
        """Switch the on-device brain size (E2B fast / E4B quality); persisted."""
        from ..providers import gemma
        size = str(body.get("size", "")).upper()
        if size not in gemma.MODELS:
            raise HTTPException(400, f"size must be one of {list(gemma.MODELS)}")
        repo, file = gemma.MODELS[size]
        engine.cfg.assistant_gguf_repo = repo
        engine.cfg.assistant_gguf_file = file
        _persist_config(engine, {"assistant_gguf_repo": repo, "assistant_gguf_file": file})
        return {"size": size, "model": file}

    @app.post("/api/assistant/tts")
    def assistant_tts(body: dict[str, Any]):
        """On-device neural TTS (Supertonic): text -> WAV. The assistant's
        spoken answers come from here (Korean and 30 other languages, local)."""
        from ..providers import supertonic_tts as tts
        from fastapi import Response
        ok, reason = tts.available()
        if not ok:
            raise HTTPException(501, reason)
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(400, "text가 필요합니다")
        voice = str(body.get("voice") or engine.cfg.assistant_tts_voice)
        if voice not in tts.VOICES:
            voice = engine.cfg.assistant_tts_voice
        try:
            pitch = float(body.get("pitch", engine.cfg.assistant_tts_pitch))
            wav = tts.synth_wav(text[:1200], voice=voice, pitch=pitch)
        except Exception as e:
            raise HTTPException(500, f"TTS 실패: {str(e)[:160]}")
        return Response(content=wav, media_type="audio/wav")

    @app.get("/api/assistant/warmup")
    def assistant_warmup():
        """Preload the on-device models and stream progress, so the first turn
        is not a silent multi-second (first-run: multi-GB download) hang."""
        cfg = engine.cfg
        stages = [
            ("brain", f"답변 모델 준비 중… ({cfg.assistant_gguf_file})", lambda: __import__(
                "lemory.providers.gemma", fromlist=["_model"])._model(
                cfg.assistant_gguf_repo, cfg.assistant_gguf_file)),
            ("stt", "음성 인식(Whisper) 준비 중…", lambda: __import__(
                "lemory.providers.whisper_stt", fromlist=["_model"])._model(
                __import__("lemory.providers.whisper_stt", fromlist=["DEFAULT_SIZE"]).DEFAULT_SIZE)),
            ("tts", "음성 합성(Supertonic) 준비 중…", lambda: __import__(
                "lemory.providers.supertonic_tts", fromlist=["_tts"])._tts()),
        ]

        def gen():
            for key, msg, load in stages:
                yield "data: " + json.dumps({"stage": key, "status": "loading", "msg": msg}, ensure_ascii=False) + "\n\n"
                try:
                    load()
                    yield "data: " + json.dumps({"stage": key, "status": "ready"}, ensure_ascii=False) + "\n\n"
                except Exception as e:
                    yield "data: " + json.dumps({"stage": key, "status": "skip", "msg": str(e)[:140]}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"stage": "done"}) + "\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/assistant/stt")
    async def assistant_stt(request: Request):
        """On-device speech-to-text (faster-whisper): the mic clip is
        transcribed locally, never sent to a cloud speech service."""
        from ..providers import whisper_stt
        ok, reason = whisper_stt.available()
        if not ok:
            raise HTTPException(501, reason)
        if int(request.headers.get("content-length", 0)) > 25_000_000:
            raise HTTPException(413, "오디오가 너무 큽니다 (최대 25MB)")
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "audio가 필요합니다")
        try:
            text = whisper_stt.transcribe(audio, lang="ko")
        except Exception as e:
            raise HTTPException(500, f"STT 실패: {str(e)[:160]}")
        return {"text": text}

    @app.post("/api/assistant/chat")
    def assistant_chat(request: Request, body: ChatBody):
        """Grounded, streaming chat over the vault. Retrieves for the latest
        user turn, streams a cited answer from the on-device assistant brain."""
        from ..retrieval.answer import SYSTEM, build_context
        cfg = engine.cfg
        msgs = [m for m in body.messages
                if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()]
        if not msgs or msgs[-1]["role"] != "user":
            raise HTTPException(400, "마지막 메시지는 사용자 메시지여야 합니다")
        question = str(msgs[-1]["content"])
        hits = engine.search(question, k=cfg.assistant_k)
        context = build_context(hits) if hits else "(관련 노트를 찾지 못했습니다.)"
        system = (SYSTEM + "\n\nNOTES (cite as [n]):\n" + context)
        history = [{"role": m["role"], "content": str(m["content"])} for m in msgs[:-1][-6:]]
        sources = [{"n": i + 1, "title": h.title, "path": h.path,
                    "snippet": h.text[:180]} for i, h in enumerate(hits)]
        if cfg.event_log:
            engine.store.log_event("assistant", client=_client(request), query=question,
                                   detail={"top": [h.path for h in hits[:3]]})
        if hits:
            engine.store.record_hits([h.doc_id for h in hits])

        def deltas():
            from ..providers import gemma
            yield from gemma.chat_stream(
                system, history, question,
                repo=cfg.assistant_gguf_repo, file=cfg.assistant_gguf_file)

        def gen():
            try:
                yield "data: " + json.dumps({"sources": sources}, ensure_ascii=False) + "\n\n"
                for delta in deltas():
                    yield "data: " + json.dumps({"delta": delta}, ensure_ascii=False) + "\n\n"
                yield "data: " + json.dumps({"done": True}) + "\n\n"
            except Exception as e:  # surface a friendly error into the stream
                yield "data: " + json.dumps({"error": str(e)[:200]}, ensure_ascii=False) + "\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/context")
    def context(max_chars: int = 2400):
        """Pre-assembled vault context (Zep-style): stats, recent activity,
        frequently referenced notes, hubs, tags — one cheap local call."""
        from ..ingestion.memory import context_block

        return {"context": context_block(engine, max_chars=max_chars)}

    @app.post("/memory")
    def memory(request: Request, body: MemoryBody):
        """Write path: persist a memory as a new Markdown note in the vault."""
        from ..ingestion.memory import save_memory

        try:
            path = save_memory(engine, body.content, title=body.title,
                               folder=body.folder, tags=body.tags,
                               client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"saved": str(path), "related": getattr(path, "related", [])}

    @app.post("/append")
    def append(request: Request, body: AppendBody):
        """Append-only write to an existing note (creates it if missing)."""
        from ..ingestion.memory import append_to_note

        try:
            rel = append_to_note(engine, body.path, body.content,
                                 client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"appended": rel}

    @app.post("/memory/trash")
    def memory_trash(request: Request, body: TrashBody):
        """Undo an AI write: move the note to <vault>/.trash. Refuses notes
        without `source:` frontmatter, so human-authored files are untouchable."""
        from ..ingestion.memory import trash_ai_note

        try:
            dest = trash_ai_note(engine, body.path, client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"trashed": body.path, "moved_to": dest}

    @app.get("/api/events")
    def api_events(kinds: str = "", limit: int = 60):
        """The middleware timeline: queries, AI writes, undos — newest first."""
        kind_list = [k for k in (s.strip() for s in kinds.split(",")) if k] or None
        return engine.store.events(kinds=kind_list, limit=min(limit, 200))

    @app.get("/api/clients")
    def api_clients(days: float = 7.0):
        """Per-client usage in the window — who is reading/writing this memory."""
        return engine.store.client_stats(days=days)

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

    @app.get("/api/related")
    def related(path: str, k: int = 8):
        """Related notes by content similarity (the note itself is the query —
        no LLM, no new embeddings)."""
        from ..retrieval.search import related_notes

        return related_notes(engine, path, k=k)

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
            "reranker": bool(getattr(cfg, "reranker", False)),
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
            if key == "provider" and coerced not in ("auto", "gemini", "openai", "local"):
                raise HTTPException(400, "provider must be auto|gemini|openai|local")
            if key == "local_embed_backend" and coerced not in ("auto", "llamacpp", "fastembed"):
                raise HTTPException(400, "local_embed_backend must be auto|llamacpp|fastembed")
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
            # json string/array syntax is valid TOML and escapes quotes,
            # backslashes (Windows paths), and serializes list values
            # (include_globs / exclude_dirs) as real arrays, not a repr string.
            lines.append(f"{k} = {json.dumps(v, ensure_ascii=False)}")
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
