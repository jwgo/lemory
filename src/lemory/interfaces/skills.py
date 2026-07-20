"""One-command skill packaging: teach any CLI assistant to use Lemory well.

The 2026 tool wave (Graphify, Understand-Anything, qmd, OpenKB) distributes
as assistant skills · a markdown file the assistant loads that says when and
how to call the tool. Lemory's MCP server already exposes the tools; the
skill closes the convenience gap: `lemory skill install claude-code` and the
assistant knows the vault is its memory, without the user explaining it.
"""

from __future__ import annotations

from pathlib import Path

_BODY = """\
## When to use Lemory

The user's Obsidian vault at `{vault}` is indexed by Lemory · treat it as
your long-term memory. Reach for it BEFORE answering anything that could
depend on the user's own notes, decisions, people, or past work, and WRITE
to it when a session produces facts worth keeping.

## Reading (search first, cite what you use)

- `lemory search "질문 그대로" --vault "{vault}"` · hybrid retrieval
  (semantic + Korean-aware BM25 + link graph). Natural questions, keywords,
  Korean, typos all work. Scope with operators: `tag:프로젝트 folder:회의록 예산`.
- `lemory ask "..." --vault "{vault}"` · grounded answer with citations
  (needs an LLM key; falls back to search results without one).
- `lemory recent --vault "{vault}"` / `lemory context --vault "{vault}"` ·
  what the user touched lately; one-call situational awareness.
- `lemory suggest-links --vault "{vault}"` · notes that mention each other
  but were never linked; offer these when the user asks about organizing.

## Writing (append-only, consolidation built in)

- `lemory remember "사실/결정 내용" --title "짧은 제목" --vault "{vault}"` ·
  saves a Markdown note, instantly searchable. If the output mentions
  `possible duplicate` or 관련 기억, tell the user which existing note it
  relates to instead of silently stacking copies.
- **Session memory (the write half of the loop):** when a conversation
  produces facts about the user · preferences, people, decisions, promises,
  updates to earlier facts · save them BEFORE the session ends: one
  `lemory remember` per fact, phrased as a dated statement ("사용자의 여동생
  이름은 김보람"). What you don't write, you won't remember tomorrow. When a
  new fact supersedes an older one, still just save the new one · retrieval
  already prefers the newer note on "요즘/최근" questions; never delete the
  old note yourself.
- Never edit vault files directly for memory purposes; `remember` and
  `append` keep provenance (`lemory_generated`) and undo working.

## Etiquette

- Quote note titles as [[wikilinks]] when telling the user where facts came from.
- Prefer one focused search over many broad ones; results are ranked, top-3
  usually suffice.
- MCP alternative: if the `lemory` MCP server is connected, use its tools
  (`search_notes`, `save_memory`, `suggest_links`, ...) instead of the CLI.
"""


def render_skill(assistant: str, vault: str) -> str:
    body = _BODY.format(vault=vault)
    if assistant == "claude-code":
        return (
            "---\n"
            "name: lemory-vault\n"
            "description: Use the user's Lemory-indexed Obsidian vault as "
            "long-term memory · search it before answering questions about "
            "the user's notes/decisions/projects, and save durable facts "
            "back into it. Trigger on questions about past work, personal "
            "context, 노트/볼트/기억 mentions, or when the user asks to "
            "remember something.\n"
            "---\n\n" + body
        )
    if assistant in ("codex", "cursor"):
        return f"# Lemory vault memory\n\n{body}"
    raise ValueError(f"unknown assistant: {assistant} (claude-code | codex | cursor)")


def skill_target(assistant: str, cwd: Path, global_install: bool) -> Path:
    home = Path.home()
    if assistant == "claude-code":
        base = home / ".claude" if global_install else cwd / ".claude"
        return base / "skills" / "lemory-vault" / "SKILL.md"
    if assistant == "codex":
        base = home / ".codex" if global_install else cwd / ".codex"
        return base / "skills" / "lemory-vault.md"
    if assistant == "cursor":
        return (cwd / ".cursor" / "rules" / "lemory-vault.mdc")
    raise ValueError(f"unknown assistant: {assistant}")
