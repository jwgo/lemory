"""Automatic session memory via agent lifecycle hooks (claude-mem pattern,
local-first edition).

`lemory hooks install claude-code` registers a SessionEnd hook in
~/.claude/settings.json. When a Claude Code session ends, Claude invokes
`lemory hook claude-code` with the hook event JSON on stdin; we read the
session transcript, ask the LLM for the handful of facts/decisions worth
keeping, and save them as ONE dated Markdown note in the vault — where it
shows up in the dashboard's AI 메모리 피드 (client: claude-code-hook) with
one-click undo, like every other write. No discipline required, nothing
invisible, nothing outside your vault.

Keyless installs skip capture gracefully (summarizing needs an LLM).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HOOK_COMMAND = "lemory hook claude-code"
MAX_TRANSCRIPT_CHARS = 60_000   # newest turns win when a session is huge
MIN_SESSION_CHARS = 400         # don't memorialize "hi" sessions

SUMMARY_SYSTEM = (
    "You extract durable memory from an AI coding session transcript. "
    "Return 3-8 short bullet points covering ONLY: decisions made, facts "
    "worth remembering later, user preferences revealed, and unfinished "
    "threads. Write bullets in the user's language. No preamble. If the "
    "session contains nothing worth remembering, reply exactly: NOTHING"
)


def parse_transcript(path: Path) -> str:
    """Claude Code transcripts are JSONL; pull out the user/assistant text."""
    parts: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text")
        else:
            continue
        text = text.strip()
        if text:
            parts.append(f"{role.upper()}: {text}")
    joined = "\n\n".join(parts)
    return joined[-MAX_TRANSCRIPT_CHARS:]


def capture_session(engine, event: dict, client: str = "claude-code-hook") -> str | None:
    """SessionEnd handler: transcript → LLM summary → one vault note.
    Returns the saved path, or None when there was nothing to keep."""
    transcript_path = event.get("transcript_path")
    if not transcript_path:
        return None
    convo = parse_transcript(Path(transcript_path))
    if len(convo) < MIN_SESSION_CHARS:
        return None
    if engine.keyless:
        return None  # summarizing needs an LLM; keyless stays read-only

    summary = engine.llm.generate(
        f"TRANSCRIPT:\n{convo}\n\nMEMORY BULLETS:",
        system=SUMMARY_SYSTEM, temperature=0.2, max_output_tokens=512,
    ).strip()
    if not summary or summary.upper().startswith("NOTHING"):
        return None

    from ..ingestion.memory import save_memory

    cwd = event.get("cwd") or ""
    project = Path(cwd).name if cwd else ""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"세션 {stamp}" + (f" — {project}" if project else "")
    return save_memory(
        engine, summary, title=title, folder="memories/sessions",
        tags=["session", "claude-code"], source="claude-code session",
        client=client,
    )


def run_hook(engine) -> int:
    """Entry point for `lemory hook claude-code`: event JSON on stdin.
    Always exits 0 — a memory hook must never break the host session."""
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        saved = capture_session(engine, event)
        if saved:
            print(json.dumps({"saved": saved}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)[:200]}), file=sys.stderr)
    return 0


# ------------------------------------------------------------------ installer
def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def install_claude_code(vault: Path, settings_path: Path | None = None) -> str:
    """Idempotently register the SessionEnd hook in Claude Code's settings.
    Existing settings are preserved; a .bak copy is written before editing."""
    sp = settings_path or claude_settings_path()
    data: dict = {}
    if sp.exists():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise ValueError(f"{sp} is not valid JSON — fix it first, not touching it")
        sp.with_suffix(".json.bak").write_text(
            sp.read_text(encoding="utf-8"), encoding="utf-8")
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault("SessionEnd", [])
    cmd = f"{HOOK_COMMAND} --vault {vault}"
    for grp in entries:
        for h in grp.get("hooks", []):
            if HOOK_COMMAND in h.get("command", ""):
                h["command"] = cmd  # update vault path in place
                break
        else:
            continue
        break
    else:
        entries.append({"hooks": [{"type": "command", "command": cmd}]})
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(sp)


def uninstall_claude_code(settings_path: Path | None = None) -> bool:
    sp = settings_path or claude_settings_path()
    if not sp.exists():
        return False
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    entries = data.get("hooks", {}).get("SessionEnd", [])
    kept = []
    removed = False
    for grp in entries:
        inner = [h for h in grp.get("hooks", []) if HOOK_COMMAND not in h.get("command", "")]
        if len(inner) != len(grp.get("hooks", [])):
            removed = True
        if inner:
            grp["hooks"] = inner
            kept.append(grp)
    if removed:
        data["hooks"]["SessionEnd"] = kept
        sp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return removed
