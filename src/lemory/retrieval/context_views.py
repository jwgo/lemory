"""Tiered context loading (L0/L1/L2) + the context tree — deterministic, LLM-0.

OpenViking's context-database contract: every entry is loadable as an
abstract (L0), an overview (L1), or full details (L2), and the store is
browsable like a filesystem — so an agent can judge relevance before
spending tokens on content. OpenViking GENERATES its tiers with an LLM at
write time and stores them as sidecar files (.abstract/.overview) in a
virtual filesystem.

A markdown note already contains its own tiers. L0 is the title + lead,
L1 is the heading skeleton with each section's opening, L2 is the file.
Deriving them at read time costs microseconds, needs no model, and can
never drift from the source — the perk of the filesystem being real.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import Engine

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

VIEW_LEVELS = ("abstract", "overview", "full")


def _split_frontmatter(content: str) -> tuple[str, str]:
    if content.startswith("---\n"):
        end = content.find("\n---", 4)
        if end != -1:
            nl = content.find("\n", end + 1)
            return content[4:end], (content[nl + 1:] if nl != -1 else "")
    return "", content


def _flatten(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


def note_abstract(title: str, content: str, limit: int = 200) -> str:
    """L0: one line — the title plus the note's lead text."""
    _, body = _split_frontmatter(content)
    lead_lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or _HEADING_RE.match(s) or s.startswith("---"):
            if lead_lines:
                break
            continue
        lead_lines.append(s.lstrip("->*• ").strip())
        if sum(len(x) for x in lead_lines) > limit:
            break
    lead = _flatten(" ".join(lead_lines), limit)
    return f"{title} — {lead}" if lead else title


def note_overview(content: str, per_section: int = 220, cap: int = 2400) -> str:
    """L1: the heading skeleton, each section represented by its opening
    text — enough to plan a drill-down, cheap enough to load speculatively."""
    fm, body = _split_frontmatter(content)
    out: list[str] = []
    tags = re.search(r"(?m)^tags:\s*(.+)$", fm)
    if tags:
        out.append(f"(tags: {tags.group(1).strip()})")

    section_text: list[str] = []
    section_budget = per_section

    def _push_section() -> None:
        nonlocal section_text, section_budget
        if section_text:
            out.append(_flatten(" ".join(section_text), per_section))
        section_text = []
        section_budget = per_section

    fence = False
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = _HEADING_RE.match(s)
        if m:
            _push_section()
            out.append(f"{'#' * len(m.group(1))} {m.group(2)}")
            continue
        if not s:
            continue
        if section_budget > 0:
            s2 = s.lstrip("->*• ").strip()
            section_text.append(s2)
            section_budget -= len(s2)
    _push_section()
    text = "\n".join(x for x in out if x)
    return text[:cap]


def note_view(engine: "Engine", rel: str, level: str = "full") -> str:
    """Read one note at a loading tier. `full` is the raw file (L2)."""
    content = engine.read_note(rel)
    if level == "full":
        return content
    if level == "overview":
        return note_overview(content)
    if level == "abstract":
        title = rel.rsplit("/", 1)[-1].removesuffix(".md")
        return note_abstract(title, content)
    raise ValueError(f"unknown level: {level} (abstract|overview|full)")


def context_tree(engine: "Engine", folder: str = "", depth: int = 2,
                 per: int = 6) -> str:
    """The vault as a browsable tree with per-note L0 lines — `ls`/`tree`
    for agent context, built from the index (no file reads, no LLM).

    Folders show note counts; each folder lists its newest `per` notes with
    their abstract line, then an elision count. `depth` bounds folder
    nesting relative to `folder`."""
    rows = engine.store.doc_overview_rows()
    prefix = folder.strip().strip("/")
    if prefix:
        rows = [r for r in rows if r["path"].startswith(prefix + "/")]
    if not rows:
        return f"(빈 폴더: {prefix or '/'})"

    by_dir: dict[str, list[dict]] = {}
    for r in rows:
        sub = r["path"][len(prefix) + 1:] if prefix else r["path"]
        parts = sub.split("/")
        d = "/".join(parts[:-1][:depth])
        by_dir.setdefault(d, []).append(r)

    lines = [f"{prefix or '(vault)'} · 노트 {len(rows)}개"]
    for d in sorted(by_dir):
        notes = sorted(by_dir[d], key=lambda r: -r["mtime"])
        indent = "  " * (d.count("/") + 1) if d else "  "
        if d:
            lines.append(f"{'  ' * d.count('/')}├─ {d.rsplit('/', 1)[-1]}/ ({len(notes)})")
        for r in notes[:per]:
            snip = (r.get("snippet") or "").strip()
            l0 = f"{r['title']} — {snip[:120]}" if snip else r["title"]
            lines.append(f"{indent}· {l0}")
        if len(notes) > per:
            lines.append(f"{indent}… 외 {len(notes) - per}개")
    return "\n".join(lines)
