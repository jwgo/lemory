"""Import ChatGPT / Claude conversation exports into the vault as Markdown.

Why: 2026's platform memory features made "my chat history is my knowledge"
normal · and export/import the standard escape hatch (Claude ships Memory
Import; Rewind/Khoj-Cloud shutdowns orphaned users mid-migration). This turns
the official data exports into plain vault notes: searchable by the same
hybrid retrieval as everything else, owned by the user, no lock-in.

Supported inputs (auto-detected):
  * ChatGPT export        conversations.json  · mapping-tree format
  * Claude export         conversations.json  · chat_messages list format

One note per conversation, under <folder>/, tagged #chat-import, dated with
the conversation's own timestamp so temporal queries ("3월에 GPT랑 얘기한
쿠버네티스 그거") work.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_SLUG_BAD = re.compile(r'[\\/:*?"<>|#^\[\]]+')
MAX_NOTE_CHARS = 60_000  # a marathon chat becomes a truncated note, not a bomb


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"\s+", " ", _SLUG_BAD.sub(" ", text)).strip()[:80].strip()
    return s or fallback


def _detect(data) -> str:
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            if "mapping" in first:
                return "chatgpt"
            if "chat_messages" in first:
                return "claude"
    raise ValueError("unrecognized export format · expected a ChatGPT or "
                     "Claude conversations.json")


def _chatgpt_messages(conv: dict) -> list[tuple[str, str]]:
    """Flatten the mapping tree in chronological order."""
    rows = []
    for node in (conv.get("mapping") or {}).values():
        msg = node.get("message") if isinstance(node, dict) else None
        if not msg:
            continue
        role = (msg.get("author") or {}).get("role", "")
        if role not in ("user", "assistant"):
            continue
        parts = (msg.get("content") or {}).get("parts") or []
        text = "\n".join(p for p in parts if isinstance(p, str)).strip()
        if text:
            rows.append((msg.get("create_time") or 0, role, text))
    rows.sort(key=lambda r: r[0])
    return [(role, text) for _ts, role, text in rows]


def _claude_messages(conv: dict) -> list[tuple[str, str]]:
    out = []
    for m in conv.get("chat_messages") or []:
        role = "user" if m.get("sender") == "human" else "assistant"
        text = (m.get("text") or "").strip()
        if text:
            out.append((role, text))
    return out


def _conv_date(conv: dict, fmt: str) -> str:
    if fmt == "chatgpt":
        ts = conv.get("create_time")
        if ts:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    else:
        raw = conv.get("created_at") or ""
        if raw:
            return raw[:10]
    return datetime.now().date().isoformat()


def log_assistant_session(engine, messages: list[dict], answer: str,
                          session: str = "") -> "str | None":
    """The write half of the memory loop: upsert THIS conversation as a dated
    session note, in the same Markdown layout import_conversations produces ·
    so what the user tells the assistant today is a searchable memory
    tomorrow, visible and editable in the vault like any note (that
    transparency is the undo story). Called after each completed assistant
    answer; the whole conversation is rewritten each time, so the note always
    holds the full session. Returns the vault-relative path, or None when
    `assistant_log_sessions` is off."""
    import hashlib
    import re as _re
    import time

    cfg = engine.cfg
    if not getattr(cfg, "assistant_log_sessions", False):
        return None
    vault = cfg.resolved_vault()
    folder = (cfg.assistant_log_folder or "chats").strip().strip("/") or "chats"
    base = vault / folder
    if not base.resolve().is_relative_to(vault.resolve()):
        folder, base = "chats", vault / "chats"  # never escape the vault
    base.mkdir(parents=True, exist_ok=True)

    now_ts = getattr(engine, "now", time.time)()
    date = time.strftime("%Y-%m-%d", time.localtime(now_ts))
    sid = _re.sub(r"[^A-Za-z0-9가-힣-]", "", session)[:12]
    if not sid:  # stable per conversation: derived from its first user turn
        first = next((str(m.get("content", "")) for m in messages
                      if m.get("role") == "user"), "")
        sid = hashlib.sha1(first.encode("utf-8")).hexdigest()[:8]
    title = f"{date} 어시스턴트 {sid}"
    rel = f"{folder}/{title}.md"

    who = {"user": "**나**", "assistant": "**AI**"}
    turns = [m for m in messages if m.get("role") in who and str(m.get("content", "")).strip()]
    turns.append({"role": "assistant", "content": answer})
    body = "\n\n".join(f"{who[m['role']]}: {str(m['content']).strip()}" for m in turns)
    if len(body) > MAX_NOTE_CHARS:
        body = body[:MAX_NOTE_CHARS] + "\n\n> (truncated)"
    (base / f"{title}.md").write_text(
        f"---\ndate: {date}\nsource: assistant\nlemory_generated: true\n"
        f"tags: [chat-import]\n---\n\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )
    engine.index(paths={rel})
    return rel


def import_conversations(engine, file: Path, folder: str = "chats",
                         limit: int | None = None) -> list[str]:
    """Write one Markdown note per conversation. Returns vault-relative paths.
    Existing notes with the same name are left untouched (safe to re-run on a
    newer export · only new conversations are added)."""
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    fmt = _detect(data)
    vault = engine.cfg.resolved_vault()
    base = vault / folder.strip().strip("/")
    # is_relative_to (vs a bare startswith) rejects sibling-prefix escapes like
    # "../<vaultname>Secrets" that share the vault's path prefix but sit outside it
    if not base.resolve().is_relative_to(vault.resolve()):
        raise ValueError(f"folder escapes the vault: {folder}")
    base.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for conv in data[:limit] if limit else data:
        msgs = _chatgpt_messages(conv) if fmt == "chatgpt" else _claude_messages(conv)
        if not msgs:
            continue
        date = _conv_date(conv, fmt)
        title = _slug(conv.get("title") or conv.get("name") or "", f"chat {date}")
        target = base / f"{date} {title}.md"
        if target.exists():  # idempotent re-import
            continue
        who = {"user": "**나**", "assistant": "**AI**"}
        body_parts = [f"{who[role]}: {text}" for role, text in msgs]
        body = "\n\n".join(body_parts)
        if len(body) > MAX_NOTE_CHARS:
            body = body[:MAX_NOTE_CHARS] + "\n\n> (truncated)"
        target.write_text(
            f"---\ndate: {date}\nsource: {fmt}\nlemory_generated: true\n"
            f"tags: [chat-import]\n---\n\n"
            f"# {title}\n\n{body}\n",
            encoding="utf-8",
        )
        written.append(str(target.relative_to(vault)))

    if written:
        engine.index(paths=set(written))
    return written
