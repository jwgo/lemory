"""Agent onboarding: managed AGENTS.md guidance + CLI-agent detection.

Absorbed from Tolaria's strongest axis (credited in docs/COMPETITIVE.md):
a vault should teach ANY agent how to use it, not just Claude. Three pieces:

1. **Managed guidance files** — `AGENTS.md` at the vault root is the
   canonical instruction file the 2026 agent wave reads (Codex, Copilot,
   OpenCode, Gemini CLI all look for it); `CLAUDE.md` and `GEMINI.md` are
   thin compatibility shims pointing at it. Lemory writes them with a
   managed marker so it can repair its own files while NEVER touching a
   user-authored one.

2. **Status detection** — each guidance file is `managed` (ours, current),
   `missing`, `broken` (empty/whitespace/stale managed template), or
   `custom` (user-authored — sacred, surfaced but untouched).

3. **Agent detection** — which agent CLIs are actually installed, with the
   exact one-line MCP hookup command for each, so `lemory agents` turns
   "install Lemory" into "every agent on this machine now has memory".
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

_MARKER = "<!-- lemory:managed:v1 -->"

_AGENTS_MD = _MARKER + """
# AGENTS.md — this vault has memory

This folder is a Markdown vault indexed by **Lemory** (local memory
middleware). Treat it as the user's long-term memory.

## Read before answering

- Search first when a question could depend on the user's notes, decisions,
  people, or past work:
  - MCP (preferred, server name `lemory`): `search_notes`, `ask_notes`,
    `recent_notes`, `related_notes`, `vault_context`
  - CLI fallback: `lemory search "question as-is" --vault "{vault}"`
- Natural questions, keywords, Korean, and typos all work. Scope with
  `tag:x folder:y`. Results are ranked — the top 3 usually suffice.
- Cite note titles as [[wikilinks]] when you use them.

## Write what's worth remembering

- Save durable facts (decisions, preferences, people, promises, updates)
  BEFORE the session ends — one fact per note:
  - MCP: `save_memory` · CLI: `lemory remember "fact" --title "short title"`
- Duplicates are detected and related notes linked automatically. If the
  result mentions a possible duplicate, tell the user instead of stacking
  copies. Never delete an outdated note — retrieval prefers newer facts.
- Do NOT hand-edit files under `memories/` or `chats/`; `save_memory` keeps
  provenance and undo working. Editing other notes directly is fine — the
  watcher reindexes within seconds.

## Rules

- A note whose frontmatter says `lemory: false` is private: never read,
  quote, or index it.
- Keep new notes small and entity-titled (person/project/topic); wikilinks
  between notes power multi-hop retrieval.
- Dashboard (`lemory serve` → http://127.0.0.1:8377) shows every AI read and
  write with one-click undo — assume the user reviews the trail.
"""

_CLAUDE_SHIM = _MARKER + """
# CLAUDE.md

See **AGENTS.md** in this folder — canonical instructions for using this
vault's Lemory memory (search first, save durable facts, respect
`lemory: false`).
"""

_GEMINI_SHIM = _MARKER + """
# GEMINI.md

See **AGENTS.md** in this folder — canonical instructions for using this
vault's Lemory memory.
"""

_FILES = {
    "AGENTS.md": _AGENTS_MD,
    "CLAUDE.md": _CLAUDE_SHIM,
    "GEMINI.md": _GEMINI_SHIM,
}


def _render(name: str, vault: Path) -> str:
    return _FILES[name].format(vault=str(vault))


def guidance_status(vault: Path) -> dict[str, str]:
    """Per-file status: managed | missing | broken | custom.

    `custom` (user-authored) is sacred — install/repair never touches it.
    `broken` = empty or whitespace-only. A managed file whose content
    drifted from the current template still counts as managed (repair
    refreshes it); a file WITHOUT our marker is the user's."""
    out: dict[str, str] = {}
    for name in _FILES:
        p = vault / name
        if not p.exists():
            out[name] = "missing"
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out[name] = "broken"
            continue
        if not text.strip():
            out[name] = "broken"
        elif _MARKER in text:
            out[name] = "managed"
        else:
            out[name] = "custom"
    return out


def install_guidance(vault: Path, refresh: bool = False) -> dict[str, str]:
    """Create/repair managed guidance files. Returns {file: action} where
    action is written | refreshed | kept (custom untouched) | current."""
    actions: dict[str, str] = {}
    status = guidance_status(vault)
    for name in _FILES:
        st = status[name]
        target = vault / name
        if st == "custom":
            actions[name] = "kept"
            continue
        content = _render(name, vault)
        if st == "managed":
            if refresh and target.read_text(encoding="utf-8", errors="replace") != content:
                target.write_text(content, encoding="utf-8")
                actions[name] = "refreshed"
            else:
                actions[name] = "current"
            continue
        target.write_text(content, encoding="utf-8")  # missing | broken
        actions[name] = "written"
    return actions


# --------------------------------------------------------------- agent detect
@dataclass
class AgentInfo:
    key: str
    label: str
    binary: str
    installed: bool
    hookup: str  # the one-liner that gives this agent Lemory memory


_AGENTS: list[tuple[str, str, str, str]] = [
    # (key, label, binary, hookup command template)
    ("claude-code", "Claude Code", "claude",
     'claude mcp add lemory -- lemory mcp --vault "{vault}" --client claude-code'),
    ("codex", "Codex CLI", "codex",
     'codex mcp add lemory -- lemory mcp --vault "{vault}" --client codex'),
    ("gemini", "Gemini CLI", "gemini",
     'gemini mcp add lemory lemory mcp --vault "{vault}" --client gemini'),
    ("copilot", "GitHub Copilot CLI", "copilot",
     "AGENTS.md에 CLI 사용법 포함 — 추가 설정 없이 동작 (MCP는 copilot 설정에서 lemory 추가)"),
    ("opencode", "OpenCode", "opencode",
     "opencode 설정(mcp)에 다음 추가: command=lemory args=[mcp, --vault, {vault}]"),
    ("cursor", "Cursor", "cursor",
     '.cursor/mcp.json에 추가: {{"lemory": {{"command": "lemory", "args": ["mcp", "--vault", "{vault}", "--client", "cursor"]}}}}'),
]

_EXTRA_BIN_DIRS = (
    "~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin",
    "~/.npm-global/bin", "~/.volta/bin", "~/.bun/bin",
)


def _find_binary(binary: str) -> bool:
    if shutil.which(binary):
        return True
    for d in _EXTRA_BIN_DIRS:
        p = Path(d).expanduser() / binary
        if p.exists():
            return True
    return False


def detect_agents(vault: Path) -> list[AgentInfo]:
    """Which agent CLIs exist on this machine, each with its Lemory hookup
    one-liner. GUI-launched shells miss PATH entries, so a few well-known
    install dirs are checked too (Tolaria-style detection, minus the zoo)."""
    out = []
    for key, label, binary, hook in _AGENTS:
        out.append(AgentInfo(
            key=key, label=label, binary=binary,
            installed=_find_binary(binary),
            hookup=hook.format(vault=str(vault)),
        ))
    return out
