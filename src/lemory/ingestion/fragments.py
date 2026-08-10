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
# only job is to be the same one everywhere. `belief` is the eighth, absorbed
# from Hindsight's opinions network: evidence (fact) and inference (belief)
# are different things, and only the latter carries a confidence and gets
# REVISED · re-remembering the same belief title updates the note in place
# and appends to its 변천 trail instead of minting a duplicate.
FRAGMENT_TYPES = (
    "fact",        # a stable truth: "배포 포트는 15000"
    "decision",    # a choice and its reason
    "error",       # a failure and (once resolved) its fix
    "preference",  # how the user wants things done
    "procedure",   # a repeatable sequence of steps
    "relation",    # how two things connect
    "episode",     # what happened in a session
    "belief",      # an inference with confidence, revisable as evidence lands
)

STATUSES = ("open", "resolved", "blocked")

# degenerate-content guard (Hindsight's _is_degenerate_text, vault-sized):
# an agent in a retry loop happily remembers "..." forever · reject anything
# that carries no letter, digit or Hangul at all
_HAS_CONTENT = re.compile(r"[0-9A-Za-z가-힣]")


def _reject_degenerate(content: str) -> None:
    if not (content or "").strip() or not _HAS_CONTENT.search(content):
        raise ValueError(
            "degenerate fragment: content carries no information "
            f"({content.strip()[:20]!r})")

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
    confidence: float | None = None,
):
    """Write one typed fragment into the vault. Returns the vault-relative
    path (carrying `.related` from the consolidation pass).

    An `error` with no explicit status is born `open` — an unresolved failure
    is the single most useful thing to hand the next session, and it only
    stays useful if forgetting to mark it defaults to "still broken".

    A `belief` with a stable title is REVISED, not duplicated: if the note
    already exists, its statement and confidence are updated in place and the
    superseded statement is appended to a `## 변천` trail — Hindsight's
    belief-updating, as a plain markdown edit you can read in Obsidian."""
    _reject_degenerate(content)
    ftype = (type or "fact").strip().lower()
    st = (status or "").strip().lower()
    if not st and ftype == "error":
        st = "open"
    conf = None
    if ftype == "belief":
        conf = 0.6 if confidence is None else max(0.0, min(1.0, float(confidence)))
    elif confidence is not None:
        conf = max(0.0, min(1.0, float(confidence)))

    if ftype == "belief" and title.strip():
        vault = engine.cfg.resolved_vault()
        rel = f"{folder}/{title.strip()}.md"
        target = _safe_target(vault, rel)
        if target.is_file():
            return _revise_belief(engine, target, content, conf, client=client)

    meta = {
        "type": ftype,
        "topic": topic.strip(),
        "case": normalize_case(case),
        "phase": phase.strip(),
        "status": st,
        "anchor": True if anchor else None,  # absent when not pinned
        "confidence": conf,
        "remembered_at": datetime.now().isoformat(timespec="seconds"),
    }
    return save_memory(
        engine, content, title=title, folder=folder, tags=tags or [],
        client=client, meta=meta,
    )


_CONF_RE = re.compile(r"(?m)^(confidence:\s*)([\d.]+)\s*$")
_REMEMBERED_RE = re.compile(r"(?m)^(remembered_at:\s*)(\S+)\s*$")
# an unbounded revision trail is how history features die (Hindsight capped
# observation history at 50 after an unbounded-JSONB blowup wedged banks)
_TRAIL_MAX = 50


def _revise_belief(engine, target, content: str, confidence: float | None,
                   client: str = "") -> str:
    """Update a belief note in place: new statement on top, new confidence in
    frontmatter, and the superseded statement appended to the `## 변천` trail
    (chronological, never overwritten — the same rule scenes follow)."""
    vault = engine.cfg.resolved_vault()
    raw = target.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    fm_block, body = (m.group(1), m.group(2)) if m else ("", raw)

    old_conf = None
    cm = _CONF_RE.search(fm_block)
    if cm:
        try:
            old_conf = float(cm.group(2))
        except ValueError:
            pass
    new_conf = confidence if confidence is not None else (old_conf or 0.6)

    # the statement is the body above the trail; the trail carries history
    parts = body.split("\n## 변천", 1)
    old_statement = " ".join(parts[0].split())
    stamp = datetime.now().strftime("%Y-%m-%d")
    conf_note = (f"{old_conf:.2f}→{new_conf:.2f}" if old_conf is not None
                 else f"→{new_conf:.2f}")
    raw_entries = ([ln for ln in parts[1].splitlines() if ln.startswith("- ")]
                   if len(parts) == 2 else [])
    prev_dropped = 0
    entries = []
    for ln in raw_entries:
        m2 = re.match(r"- \(오래된 개정 (\d+)건 생략\)", ln)
        if m2:
            prev_dropped += int(m2.group(1))
        else:
            entries.append(ln)
    entries.append(f"- {stamp} · 확신도 {conf_note} · 이전: {old_statement[:160]}")
    dropped = prev_dropped + max(0, len(entries) - _TRAIL_MAX)
    entries = entries[-_TRAIL_MAX:]
    if dropped > 0:
        entries = [f"- (오래된 개정 {dropped}건 생략)"] + entries
    trail = "## 변천\n" + "\n".join(entries)

    now = datetime.now().isoformat(timespec="seconds")
    if cm:
        fm_block = _CONF_RE.sub(lambda x: f"{x.group(1)}{new_conf:.2f}", fm_block)
    else:
        fm_block += f"\nconfidence: {new_conf:.2f}"
    if _REMEMBERED_RE.search(fm_block):
        fm_block = _REMEMBERED_RE.sub(lambda x: f"{x.group(1)}{now}", fm_block)

    target.write_text(f"---\n{fm_block}\n---\n\n{content.strip()}\n\n{trail}\n",
                      encoding="utf-8")
    rel = str(target.relative_to(vault))
    engine.index(paths={rel})
    if engine.cfg.event_log:
        engine.store.log_event("memory", client=client, path=rel,
                               detail={"belief_revised": True,
                                       "confidence": new_conf})
    return rel


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
