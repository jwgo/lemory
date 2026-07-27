"""Agent working memory: typed fragments, anchors, and work threads.

The read/write loop an AI coding agent needs across sessions — `remember` a
typed fragment, `recall` it scoped, `reflect` at session end, `resume_case` a
half-finished thread — expressed in the substrate Lemory already owns.

The design borrows AnchorMind's fragment taxonomy on purpose: an agent that
learned `type="decision"` somewhere else keeps the habit here, and a fragment
export from either side maps 1:1. What differs is everything underneath:

  * a fragment is a **Markdown note in the user's own vault**, not a row in a
    hosted Postgres. It is visible in Obsidian the instant it is written,
    editable by hand, diffable in git, and deletable without an API call.
  * recall runs the full hybrid stack (BM25 + vectors + RRF + link-graph
    expansion + recency), not a lone pgvector cosine. Typing narrows the
    candidate set; it does not replace ranking.
  * a case is not just a filter key. `resume_case` reconstructs the thread —
    timeline, decisions, still-open errors, the next steps the last session
    wrote down — because the fragments are linked notes, not loose rows.
  * there is no quota. The ceiling is the disk.

Boundaries kept from the rest of the write path: every fragment goes through
`save_memory` (never overwrites, dedup/consolidation pass, approval gate,
trash guard), and `type`/`case`/`status` are ordinary frontmatter, so the same
scoping works from the CLI and the web search box via `type:` operators.
"""

from __future__ import annotations

import re
from datetime import datetime

from .memory import _safe_target, save_memory

# AnchorMind's seven, verbatim — interop beats invention for a taxonomy whose
# only job is to be the same one everywhere.
FRAGMENT_TYPES = (
    "fact",        # a stable truth: "배포 포트는 15000"
    "decision",    # a choice and its reason
    "error",       # a failure and (once resolved) its fix
    "preference",  # how the user wants things done
    "procedure",   # a repeatable sequence of steps
    "relation",    # how two things connect
    "episode",     # what happened in a session
)

STATUSES = ("open", "resolved", "blocked")

# an unrecognized type is stored as-is rather than rejected: the taxonomy is a
# convention for ranking and filtering, not a schema to fight the agent over
_SLUG_SAFE = re.compile(r"[^0-9A-Za-z가-힣 _-]+")


def normalize_case(case: str) -> str:
    """Case ids come from agents and humans alike, so they are normalized to a
    comparable form (trimmed, collapsed whitespace, filesystem-safe) but NOT
    lowercased — the id is shown back to the user as they wrote it, and
    `docs_matching` compares case-insensitively anyway."""
    return re.sub(r"\s+", " ", _SLUG_SAFE.sub(" ", case)).strip()


def remember(
    engine,
    content: str,
    type: str = "fact",
    topic: str = "",
    case: str = "",
    phase: str = "",
    status: str = "",
    anchor: bool = False,
    title: str = "",
    tags: list[str] | None = None,
    folder: str = "memories",
    client: str = "",
):
    """Write one typed fragment into the vault. Returns the vault-relative
    path (carrying `.related` from the consolidation pass).

    An `error` with no explicit status is born `open` — an unresolved failure
    is the single most useful thing to hand the next session, and it only
    stays useful if forgetting to mark it defaults to "still broken"."""
    ftype = (type or "fact").strip().lower()
    st = (status or "").strip().lower()
    if not st and ftype == "error":
        st = "open"
    meta = {
        "type": ftype,
        "topic": topic.strip(),
        "case": normalize_case(case),
        "phase": phase.strip(),
        "status": st,
        "anchor": True if anchor else None,  # absent when not pinned
        "remembered_at": datetime.now().isoformat(timespec="seconds"),
    }
    return save_memory(
        engine, content, title=title, folder=folder, tags=tags or [],
        client=client, meta=meta,
    )


def set_anchor(engine, path: str, on: bool = True, client: str = "") -> str:
    """Pin (or unpin) a note as core memory — the handful of fragments worth
    injecting into every session before the agent asks anything.

    This is the one write that edits an existing note, so it is deliberately
    surgical: only the frontmatter block is touched, key by key, and the body
    is copied through byte-for-byte. A note with no frontmatter gets a minimal
    block prepended rather than being rewritten."""
    vault = engine.cfg.resolved_vault()
    rel = path if path.endswith(".md") else path + ".md"
    target = _safe_target(vault, rel)
    if not target.is_file():
        raise ValueError(f"no such note: {path}")
    raw = target.read_text(encoding="utf-8")

    if raw.startswith("---"):
        end = raw.find("\n---", 3)
    else:
        end = -1
    if end == -1:
        # no frontmatter block — add one only when pinning
        if not on:
            return str(target.relative_to(vault))
        new = f"---\nanchor: true\n---\n\n{raw.lstrip()}"
    else:
        kept = [ln for ln in raw[3:end].split("\n")
                if not re.match(r"\s*anchor\s*:", ln)]
        if on:
            kept.append("anchor: true")
        block = "\n".join(kept)
        if block.strip():
            new = f"---{block}\n---{raw[end + 4:]}"
        else:
            # unpinning emptied the block — drop it rather than leave a bare
            # `---\n---`, which the parser would read back as body content
            new = raw[end + 4:].lstrip("\n")

    target.write_text(new, encoding="utf-8")
    rel = str(target.relative_to(vault))
    engine.index(paths={rel})
    if engine.cfg.event_log:
        engine.store.log_event("append", client=client, path=rel,
                               detail={"anchor": bool(on)})
    return rel


def anchored(engine, limit: int = 12) -> list[dict]:
    """The pinned core memory, newest first."""
    ids = engine.store.docs_matching(fields={"anchor": ["true", "yes", "1"]})
    if not ids:
        return []
    docs = {d.id: d for d in engine.store.all_docs() if d.id in ids}
    rows = sorted(docs.values(), key=lambda d: -d.mtime)[:limit]
    meta = engine.store.docs_meta([d.id for d in rows])
    return [
        {"path": d.path, "title": d.title,
         "type": str(meta.get(d.id, {}).get("type", "") or ""),
         "case": str(meta.get(d.id, {}).get("case", "") or "")}
        for d in rows
    ]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {s.strip()}" for s in items if s and s.strip())


def reflect(
    engine,
    summary: str,
    decisions: list[str] | None = None,
    errors_resolved: list[str] | None = None,
    next_steps: list[str] | None = None,
    case: str = "",
    phase: str = "",
    notes_touched: list[str] | None = None,
    client: str = "",
):
    """Session close-out: persist what happened as one `episode` fragment.

    The sections are not decoration — `resume_case` reads them back. Next
    steps in particular are what turn a stopped session into a resumable one,
    and the notes touched become [[wikilinks]], which makes the episode a real
    node in the graph the retriever already walks."""
    if not summary.strip():
        raise ValueError("empty reflection summary")
    case_n = normalize_case(case)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts = [f"## 요약\n\n{summary.strip()}"]
    if decisions:
        parts.append(f"## 결정\n\n{_bullets(decisions)}")
    if errors_resolved:
        parts.append(f"## 해결한 문제\n\n{_bullets(errors_resolved)}")
    if next_steps:
        parts.append(f"## 다음 단계\n\n{_bullets(next_steps)}")
    if notes_touched:
        links = [f"[[{_link_title(n)}]]" for n in notes_touched if n and n.strip()]
        if links:
            parts.append("## 참조한 노트\n\n" + _bullets(links))
    body = "\n\n".join(parts)

    title = f"세션 {stamp}" + (f" · {case_n}" if case_n else "")
    return remember(
        engine, body, type="episode", case=case_n, phase=phase,
        title=title, folder="memories/sessions", client=client,
    )


def _link_title(note: str) -> str:
    """A wikilink targets a note's title, so a path is reduced to its stem."""
    stem = note.rsplit("/", 1)[-1]
    return stem[:-3] if stem.endswith(".md") else stem
