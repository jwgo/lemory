"""OpenAI-compatible memory proxy: any LLM client gets memory with a baseURL.

TDBAM ships a MemoryProxy service that sits in front of the model API and
injects memory into every call · that is the surface that multiplies 사용처,
because clients that will never speak MCP (SDKs, LangChain scripts, IDE
plugins, curl) all speak /v1/chat/completions. Absorbed, vault edition:

    client ──POST /v1/chat/completions──▶ lemory serve ──▶ upstream LLM
                    ▲                          │
        boot context + per-turn recall         └─ exchange captured as an L0
        injected as a system message              session note (chats/proxy/)

* Injection is TDBAM's split, collapsed: the stable top of the pyramid
  (persona + scene map via context_block) plus per-turn relevant memories
  (hybrid recall on the last user message).
* Capture closes the loop: the conversation becomes a vault session note
  (`chat-import` tagged), so distill → consolidate promote it up the
  pyramid. Any OpenAI client becomes a memory-writing client for free.
* The upstream key comes from config (proxy_upstream_key, falling back to
  the OpenAI key) · the client's own Authorization header is NOT forwarded,
  so a leaked local port never leaks through to a paid upstream.
* Streaming passes through verbatim; assistant text is re-assembled from
  the SSE deltas best-effort for capture (a parse failure loses only the
  capture, never the client's stream).
"""

from __future__ import annotations

import json
import logging
import threading

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

log = logging.getLogger("lemory.proxy")

_HOP_HEADERS = {"host", "content-length", "authorization", "connection",
                "keep-alive", "transfer-encoding", "accept-encoding"}


def _memory_system_message(engine, messages: list[dict]) -> str:
    parts = ["<lemory-memory>", engine.context(max_chars=1800)]
    last_user = next((str(m.get("content", "")) for m in reversed(messages)
                      if m.get("role") == "user"), "").strip()
    if last_user:
        try:
            hits = engine.search(last_user[:300], k=4, record=True, client="proxy")
        except Exception:
            hits = []
        if hits:
            parts.append("\n## Relevant memories (this turn)")
            parts.extend(f"- [{h.title}] {h.text[:240]}" for h in hits)
    parts.append(
        "</lemory-memory>\n위 기억은 사용자의 개인 볼트에서 왔다. 답변에 자연스럽게 "
        "활용하되, 기억에 없는 사실을 지어내지 마라.")
    return "\n".join(parts)


def _inject(engine, body: dict) -> dict:
    msgs = list(body.get("messages") or [])
    if not msgs:
        return body
    mem = {"role": "system", "content": _memory_system_message(engine, msgs)}
    # after any existing system prompt, before the conversation · the client's
    # own system prompt keeps precedence
    i = 0
    while i < len(msgs) and msgs[i].get("role") == "system":
        i += 1
    body = dict(body)
    body["messages"] = msgs[:i] + [mem] + msgs[i:]
    return body


def _capture(engine, messages: list[dict], answer: str, session: str) -> None:
    """Persist the exchange as an L0 session note (thread, best-effort)."""
    if not answer.strip() or not getattr(engine.cfg, "proxy_capture", True):
        return

    def _run():
        try:
            rel = engine.log_session(messages, answer, session=session,
                                     force=True, folder="chats/proxy")
            if rel and engine.cfg.event_log:
                engine.store.log_event("memory", client="proxy", path=rel,
                                       detail={"turns": len(messages) + 1})
        except Exception:
            log.exception("proxy capture failed")

    threading.Thread(target=_run, daemon=True).start()


def _sse_answer(chunks: list[bytes]) -> str:
    """Assistant text out of accumulated SSE bytes, best-effort."""
    text = []
    for raw in b"".join(chunks).split(b"\n"):
        line = raw.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            delta = json.loads(payload)["choices"][0].get("delta", {})
            if "content" in delta and delta["content"]:
                text.append(delta["content"])
        except Exception:
            continue
    return "".join(text)


def mount_proxy(app, engine) -> None:
    cfg = engine.cfg

    def _upstream() -> tuple[str, str]:
        base = (getattr(cfg, "proxy_upstream", "") or
                "https://api.openai.com/v1").rstrip("/")
        key = (getattr(cfg, "proxy_upstream_key", "") or
               cfg.resolved_openai_key() or "")
        if not key:
            raise HTTPException(
                502, "proxy upstream key missing: set proxy_upstream_key "
                     "(or OPENAI_API_KEY) in lemory.toml / env")
        return base, key

    @app.get("/v1/models")
    async def proxy_models():
        base, key = _upstream()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{base}/models",
                                 headers={"Authorization": f"Bearer {key}"})
        return json.loads(r.text)

    @app.post("/v1/chat/completions")
    async def proxy_chat(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "invalid JSON body")
        engine.index()
        original_msgs = list(body.get("messages") or [])
        body = _inject(engine, body)
        base, key = _upstream()
        session = request.headers.get("x-lemory-session", "")
        headers = {"Authorization": f"Bearer {key}",
                   "Content-Type": "application/json"}

        if body.get("stream"):
            client = httpx.AsyncClient(timeout=None)
            req = client.build_request("POST", f"{base}/chat/completions",
                                       json=body, headers=headers)
            resp = await client.send(req, stream=True)
            if resp.status_code != 200:
                detail = (await resp.aread()).decode("utf-8", "ignore")[:400]
                await client.aclose()
                raise HTTPException(resp.status_code, detail)
            collected: list[bytes] = []

            async def _relay():
                try:
                    async for chunk in resp.aiter_bytes():
                        collected.append(chunk)
                        yield chunk
                finally:
                    await client.aclose()
                    _capture(engine, original_msgs, _sse_answer(collected),
                             session)

            return StreamingResponse(_relay(), media_type="text/event-stream")

        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(f"{base}/chat/completions", json=body,
                                  headers=headers)
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text[:400])
        out = json.loads(r.text)
        try:
            answer = out["choices"][0]["message"]["content"] or ""
        except Exception:
            answer = ""
        _capture(engine, original_msgs, answer, session)
        return out
