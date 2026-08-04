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
    "memory_approval": bool,
    "auto_consolidate": bool,
    "proxy_capture": bool,
    "semantic_links": bool,
    "context_neighbors": bool,
    "usage_prior": float,
    "assistant_log_sessions": bool,
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
    "chat_burst_chunking": bool,
    "informativeness_prior": float,
    "default_scope": str,
    "git_autocommit": bool,
    "answer_n_ctx": int,
    "answer_gpu_layers": int,
}

def _version() -> str:
    try:
        from importlib.metadata import version

        return version("lemory")
    except Exception:
        return "unknown"


ACTIVITY_KEY = "console_activity"
ACTIVITY_MAX = 60


class AskBody(BaseModel):
    question: str
    k: int = 8


class ChatBody(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": str}, ...]
    session: str = ""  # client-generated id so same-day conversations don't merge


class IndexBody(BaseModel):
    full: bool = False


class MemoryBody(BaseModel):
    content: str
    title: str = ""
    folder: str = "memories"
    tags: list[str] = []


class FragmentBody(BaseModel):
    content: str
    type: str = "fact"
    topic: str = ""
    case: str = ""
    phase: str = ""
    status: str = ""
    anchor: bool = False
    title: str = ""
    tags: list[str] = []


class AnchorBody(BaseModel):
    path: str
    pinned: bool = True


class AppendBody(BaseModel):
    path: str
    content: str


class TrashBody(BaseModel):
    path: str


def remote_auth_error(client_host: str, auth_header: str,
                      api_token: str) -> tuple[str, int] | None:
    """Remote access (the mobile story): non-localhost CLIENTS must present
    the configured Bearer token. Localhost stays tokenless so the desktop
    dashboard/plugin work with zero setup; with no token configured,
    non-localhost requests are refused outright (never silently open).
    ('testclient' is starlette's TestClient pseudo-host · local by
    definition, never seen by a real socket.)"""
    if client_host in ("127.0.0.1", "::1", "localhost", "testclient", ""):
        return None
    if not api_token:
        return ("remote access disabled: set api_token in lemory.toml "
                "and send 'Authorization: Bearer <token>'", 403)
    if auth_header != f"Bearer {api_token}":
        return ("invalid token", 401)
    return None


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
                state["watcher_alive"] = True
                try:
                    engine.watch(on_sync=lambda r: _log_activity(engine, "watch", r)
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

        def _auto_consolidate():
            """Background pyramid promotion (opt-in, cfg.auto_consolidate):
            poll every minute; when new atoms have been idle for a few
            minutes, run one consolidate pass. The toggle is read each tick,
            so flipping it in 설정 takes effect without a restart."""
            while not state.get("shutdown"):
                time.sleep(60)
                if not getattr(engine.cfg, "auto_consolidate", False):
                    continue
                try:
                    if engine.consolidate_due():
                        rep = engine.consolidate()
                        if rep.atoms:
                            log.info("auto-consolidate: %d atoms → %d scene(s)%s",
                                     rep.atoms,
                                     len(rep.scenes_created) + len(rep.scenes_updated),
                                     ", persona" if rep.persona else "")
                except Exception:
                    # a failed pass must never kill the loop · atoms stay
                    # pending and the next tick retries
                    log.exception("auto-consolidate pass failed")

        threading.Thread(target=_auto_consolidate, daemon=True,
                         name="lemory-consolidate").start()
        yield
        state["shutdown"] = True

    app = FastAPI(title="Lemory", version=_version(), lifespan=lifespan)

    # DNS-rebinding defense. This server has no auth and exposes write/delete
    # endpoints (/memory, /append, /memory/trash, /index). It binds 127.0.0.1,
    # but a malicious web page can rebind its own hostname to 127.0.0.1 and
    # POST to it from the victim's browser — CORS doesn't stop that, because
    # after rebinding the request is same-origin. The rebound request still
    # carries the attacker's Host header, so a hostname allowlist blocks it
    # while letting real localhost clients (browser console, Obsidian) through.
    from starlette.responses import PlainTextResponse

    _ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", ""} | {
        h.strip().lower() for h in engine.cfg.allowed_hosts if h.strip()
    }

    @app.middleware("http")
    async def _host_guard(request, call_next):
        host = request.headers.get("host", "")
        # strip port: "127.0.0.1:8377" -> "127.0.0.1", "[::1]:8377" -> "::1"
        hostname = host.rsplit(":", 1)[0] if ":" in host and not host.endswith("]") \
            else host
        hostname = hostname.strip("[]").lower()
        if hostname not in _ALLOWED_HOSTS:
            return PlainTextResponse(
                "host not allowed (DNS-rebinding guard)", status_code=421)
        client_host = request.client.host if request.client else ""
        err = remote_auth_error(client_host, request.headers.get("authorization", ""),
                                engine.cfg.api_token)
        if err:
            return PlainTextResponse(err[0], status_code=err[1])
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

    @app.get("/health")
    def health():
        """Liveness + readiness in one cheap call (the daemon's probe target).
        Always 200 once the app is up; `ok` is the readiness verdict."""
        st = engine.status()
        return {
            "ok": True,
            "version": _version(),
            "services": {
                "watcher": state["watcher_alive"],
                "auto_consolidate": bool(getattr(engine.cfg, "auto_consolidate", False)),
                "proxy": bool(engine.cfg.resolved_openai_key()
                              or getattr(engine.cfg, "proxy_upstream_key", "")),
            },
            "index": {"documents": st["documents"], "chunks": st["chunks"],
                      "last_sync": st["last_sync"]},
            "uptime_seconds": int(time.time() - state["started_at"]),
        }

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
                cfg.assistant_gguf_repo, cfg.assistant_gguf_file,
                cfg.answer_n_ctx, cfg.answer_gpu_layers)),
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
        """Grounded, streaming chat over the vault · transport only, the
        conversation logic lives in lemory.assistant."""
        from .. import assistant as asst

        cfg = engine.cfg
        msgs = [m for m in body.messages
                if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()]
        if not msgs or msgs[-1]["role"] != "user":
            raise HTTPException(400, "마지막 메시지는 사용자 메시지여야 합니다")
        question = str(msgs[-1]["content"])

        mem = asst.remember_intent(question)
        if mem is not None:
            confirm = asst.save_from_chat(engine, mem,
                                          client=_client(request) or "assistant")

            def gen_mem():
                yield "data: " + json.dumps({"sources": []}, ensure_ascii=False) + "\n\n"
                yield "data: " + json.dumps({"delta": confirm}, ensure_ascii=False) + "\n\n"
                yield "data: " + json.dumps({"done": True}, ensure_ascii=False) + "\n\n"

            return StreamingResponse(gen_mem(), media_type="text/event-stream")

        turn = asst.prepare_chat_turn(engine, msgs, client=_client(request))

        def deltas():
            from ..providers import gemma
            yield from gemma.chat_stream(
                turn.system, turn.history, turn.question,
                repo=cfg.assistant_gguf_repo, file=cfg.assistant_gguf_file,
                n_ctx=cfg.answer_n_ctx, gpu_layers=cfg.answer_gpu_layers)

        def gen():
            try:
                yield "data: " + json.dumps({"sources": turn.sources}, ensure_ascii=False) + "\n\n"
                parts: list[str] = []
                for delta in deltas():
                    parts.append(delta)
                    yield "data: " + json.dumps({"delta": delta}, ensure_ascii=False) + "\n\n"
                logged = None
                try:  # capture never breaks the stream
                    logged = engine.log_session(msgs, "".join(parts), session=body.session)
                except Exception:
                    log.warning("assistant session logging failed", exc_info=True)
                yield "data: " + json.dumps({"done": True, "logged": logged},
                                            ensure_ascii=False) + "\n\n"
            except Exception as e:  # surface a friendly error into the stream
                yield "data: " + json.dumps({"error": str(e)[:200]}, ensure_ascii=False) + "\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/context")
    def context(max_chars: int = 2400):
        """Pre-assembled vault context (Zep-style): stats, recent activity,
        frequently referenced notes, hubs, tags · one cheap local call."""
        return {"context": engine.context(max_chars=max_chars)}

    @app.post("/memory")
    def memory(request: Request, body: MemoryBody):
        """Write path: persist a memory as a new Markdown note in the vault."""
        try:
            path = engine.remember_note(body.content, title=body.title,
                                        folder=body.folder, tags=body.tags,
                                        client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"saved": str(path), "related": getattr(path, "related", [])}

    # ---- agent working memory -------------------------------------------

    @app.post("/memory/fragment")
    def memory_fragment(request: Request, body: FragmentBody):
        """Write a typed fragment (fact/decision/error/preference/procedure/
        relation/episode), optionally tied to a work thread."""
        try:
            path = engine.remember(body.content, type=body.type, topic=body.topic,
                                   case=body.case, phase=body.phase, status=body.status,
                                   anchor=body.anchor, title=body.title, tags=body.tags,
                                   client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"saved": str(path), "type": body.type,
                "related": getattr(path, "related", [])}

    @app.get("/api/recall")
    def api_recall(q: str = "", type: str = "", case: str = "", topic: str = "",
                   status: str = "", since_days: int = 0, k: int = 8):
        """Scoped fragment recall, ranked by the hybrid retriever."""
        engine.index()
        return {"results": engine.recall(query=q, type=type, case=case,
                                         topic=topic, status=status,
                                         since_days=since_days, k=k)}

    @app.get("/api/cases")
    def api_cases(limit: int = 20):
        """Work threads, most recently touched first, with unresolved counts."""
        engine.index()
        return {"cases": engine.open_cases(limit=limit)}

    @app.get("/api/case")
    def api_case(case: str):
        """One work thread, reconstructed: next steps, unresolved items,
        decisions, timeline."""
        engine.index()
        try:
            return engine.resume_case(case)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/memory/anchor")
    def memory_anchor(request: Request, body: AnchorBody):
        """Pin/unpin a note as core memory (injected into /context)."""
        try:
            rel = engine.set_anchor(body.path, on=body.pinned,
                                    client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"path": rel, "anchor": body.pinned}

    @app.get("/api/anchors")
    def api_anchors(limit: int = 12):
        """The pinned core memory set."""
        engine.index()
        return {"anchors": engine.anchors(limit=limit)}

    # ---- memory pyramid (L2 scenes + L3 persona) ------------------------

    @app.get("/api/persona")
    def api_persona():
        """The L3 persona note: body + whether it exists."""
        engine.index()
        body = engine.persona(max_chars=4000)
        return {"path": engine.cfg.persona_note, "body": body,
                "exists": bool(body)}

    @app.get("/api/scenes")
    def api_scenes(limit: int = 24):
        """The L2 scene map, hottest first."""
        engine.index()
        return {"scenes": engine.scene_map(limit=limit)}

    @app.post("/memory/consolidate")
    def memory_consolidate(request: Request):
        """Run one pyramid promotion pass (L1 atoms → scenes → persona).
        Incremental; returns what happened. Uses the LLM when available,
        deterministic fallback otherwise."""
        engine.index()
        try:
            rep = engine.consolidate()
        except Exception as e:
            raise HTTPException(500, f"consolidate failed: {e}")
        return {"atoms": rep.atoms, "scenes_updated": rep.scenes_updated,
                "scenes_created": rep.scenes_created,
                "absorbed_into_existing": rep.scenes_absorbed,
                "persona": rep.persona or None, "used_llm": rep.llm}

    @app.get("/api/skills")
    def api_skills():
        """Reusable skill notes extracted from finished work threads."""
        engine.index()
        return {"skills": engine.skills()}

    @app.post("/memory/skills-extract")
    def memory_skills_extract(request: Request):
        """Run the skill gate over finished cases; writes 스킬/*.md for the
        few that pass. Empty result is the normal outcome."""
        engine.index()
        try:
            written = engine.extract_skills()
        except Exception as e:
            raise HTTPException(500, f"skill extraction failed: {e}")
        return {"skills_written": written}

    @app.post("/append")
    def append(request: Request, body: AppendBody):
        """Append-only write to an existing note (creates it if missing)."""
        try:
            rel = engine.append_note(body.path, body.content,
                                     client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"appended": rel}

    @app.post("/memory/trash")
    def memory_trash(request: Request, body: TrashBody):
        """Undo an AI write: move the note to <vault>/.trash. Refuses notes
        without `source:` frontmatter, so human-authored files are untouchable."""
        try:
            dest = engine.trash_note(body.path, client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"trashed": body.path, "moved_to": dest}

    @app.get("/api/pending")
    def api_pending():
        """AI writes awaiting approval (memory_approval mode)."""
        return engine.pending_notes()

    @app.get("/api/drift")
    def api_drift():
        """Memory-vs-reality scan: broken wikilinks, dead file links,
        unresolved duplicate flags (same engine as `lemory drift`)."""
        return engine.find_drift()

    @app.get("/api/suggest_links")
    def api_suggest_links(path: str = "", k: int = 12):
        """Unlinked mentions as [[link]] proposals with sentence evidence."""
        return engine.link_suggestions(path=path or None, k=k)

    @app.post("/memory/approve")
    def memory_approve(request: Request, body: TrashBody):
        """Approve a pending AI-written note so it enters the index.
        (Reject = the existing /memory/trash undo.)"""
        try:
            rel = engine.approve_note(body.path, client=_client(request))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"approved": rel}

    @app.get("/api/events")
    def api_events(kinds: str = "", limit: int = 60):
        """The middleware timeline: queries, AI writes, undos · newest first."""
        kind_list = [k for k in (s.strip() for s in kinds.split(",")) if k] or None
        return engine.store.events(kinds=kind_list, limit=min(limit, 200))

    @app.get("/api/clients")
    def api_clients(days: float = 7.0):
        """Per-client usage in the window · who is reading/writing this memory."""
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

    @app.get("/api/conflicts")
    def conflicts(threshold: float = 0.80, limit: int = 30):
        """Cross-note disagreements (number/negation) + duplicate candidates."""
        return [
            {
                "kind": c.kind, "similarity": round(c.similarity, 3),
                "detail": c.detail,
                "a": {"path": c.a.path, "title": c.a.title, "text": c.a.text[:240]},
                "b": {"path": c.b.path, "title": c.b.title, "text": c.b.text[:240]},
            }
            for c in engine.conflicts(threshold=threshold, limit=limit)
        ]

    @app.get("/api/related")
    def related(path: str, k: int = 8):
        """Related notes by content similarity (the note itself is the query ·
        no LLM, no new embeddings)."""
        return engine.related(path, k=k)

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

    # OpenAI-compatible memory proxy: /v1/chat/completions + /v1/models ·
    # any client that can change a baseURL gets read+write memory
    from .proxy import mount_proxy

    mount_proxy(app, engine)

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
        from ..config import tomllib  # 3.10-safe (tomli fallback)
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
