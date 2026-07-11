"""Write path: let AI clients persist memories INTO the vault as Markdown.

This is the 2026 table-stakes feature of every memory product (mem0 `add()`,
basic-memory `write_note`, supermemory ingest): a conversation shouldn't be
read-only. Lemory's twist is that a "memory" is not a row in a proprietary
store — it is a plain Markdown note in the user's own vault, immediately
visible in Obsidian, versionable, and indexed by the same pipeline as
everything else. No lock-in, full provenance.

Safety rules:
  * writes never leave the vault root (path traversal is rejected)
  * `save_memory` never overwrites — name collisions get a numeric suffix
  * `append_to_note` only appends; it cannot rewrite existing content
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

_SLUG_BAD = re.compile(r'[\\/:*?"<>|#^\[\]]+')


def _slug(text: str, fallback: str) -> str:
    s = _SLUG_BAD.sub(" ", text).strip()
    s = re.sub(r"\s+", " ", s)[:80].strip()
    return s or fallback


def _safe_target(vault: Path, rel: str) -> Path:
    target = (vault / rel).resolve()
    if not str(target).startswith(str(vault.resolve()) + "/") and target != vault.resolve():
        raise ValueError(f"path escapes the vault: {rel}")
    return target


class SavedMemory(str):
    """The vault-relative path of the saved note (a plain str for every
    existing caller), carrying the consolidation result as `.related`."""

    related: list[dict] = []


_TOKEN_RE = re.compile(r"[a-z0-9가-힣]+")


def _token_overlap(a: str, b: str) -> float:
    """Jaccard over content tokens — the lexical confirmation for dedup."""
    ta = {t for t in _TOKEN_RE.findall(a.lower()) if len(t) > 1}
    tb = {t for t in _TOKEN_RE.findall(b.lower()) if len(t) > 1}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_related_memories(engine, content: str, exclude_rel: str = "",
                          k: int = 3) -> list[dict]:
    """The consolidation half of a second brain: what does the vault ALREADY
    know that this new memory relates to — or repeats?

    mem0/Zep resolve this with an LLM pass that rewrites or deletes old
    facts. Lemory links instead of destroying: the new note gets `related:`
    wikilinks and a duplicate flag, the human (or agent) decides. Zero LLM —
    cosine over the existing index plus a lexical-overlap confirmation for
    the near-duplicate call (two thresholds beat one: embedder cosine scales
    vary, token overlap doesn't). Empty in keyless mode (no vectors)."""
    try:
        qv = engine.embed_query_cached(content[:1200])
    except Exception:
        return []
    if qv is None:
        return []
    cfg = engine.cfg
    cand = engine.store.vector_search(qv, 24)
    metas = engine.store.get_chunks([cid for cid, _ in cand])
    best: dict[str, dict] = {}
    for cid, sim in cand:
        m = metas.get(cid)
        if m is None or m.path == exclude_rel:
            continue
        cur = best.get(m.path)
        if cur is None or sim > cur["sim"]:
            best[m.path] = {"path": m.path, "title": m.title,
                            "sim": float(sim), "text": m.text}
    out = []
    for r in sorted(best.values(), key=lambda x: -x["sim"])[:k]:
        if r["sim"] < cfg.memory_related_sim:
            continue
        overlap = _token_overlap(content, r["text"])
        out.append({
            "path": r["path"], "title": r["title"], "sim": round(r["sim"], 3),
            "near_duplicate": bool(r["sim"] >= cfg.memory_dedup_sim
                                   and overlap >= cfg.memory_dedup_overlap),
        })
    return out


def save_memory(
    engine,
    content: str,
    title: str = "",
    folder: str = "memories",
    tags: list[str] | None = None,
    source: str = "assistant",
    client: str = "",
) -> SavedMemory:
    """Persist a memory as a new Markdown note. Returns the vault-relative
    path (a str subclass carrying the consolidation result as `.related`)."""
    if not content.strip():
        raise ValueError("empty memory content")
    vault = engine.cfg.resolved_vault()
    today = datetime.now().date().isoformat()
    name = _slug(title or content.strip().splitlines()[0], f"memory {today}")
    folder = folder.strip().strip("/") or "memories"
    base = _safe_target(vault, folder)
    base.mkdir(parents=True, exist_ok=True)

    # consolidation pass BEFORE writing: what the vault already knows.
    # (computed against the index as-is, so the new note can't match itself)
    related = find_related_memories(engine, content) if engine.cfg.memory_relate else []

    tag_line = ""
    if tags:
        clean = [c for t in tags if (c := t.strip().lstrip("#"))]
        if clean:
            tag_line = "tags: [" + ", ".join(clean) + "]\n"
    related_line = ""
    if related:
        links = ", ".join(f'"[[{r["title"]}]]"' for r in related)
        related_line = f"related: [{links}]\n"
        dup = next((r for r in related if r["near_duplicate"]), None)
        if dup:
            related_line += f'possible_duplicate_of: "[[{dup["title"]}]]"\n'
    # lemory_generated is the ONLY thing the trash guard trusts — an
    # unambiguous machine marker a human would never type. `source:` is
    # human-facing metadata (and a common human field: web clippings, quotes),
    # so it must NOT gate deletion.
    body = (
        f"---\ndate: {today}\nsource: {source}\nlemory_generated: true\n"
        f"{tag_line}{related_line}---\n\n"
        f"{content.strip()}\n"
    )
    # exclusive create in the collision loop: `open(..., "x")` fails if the
    # name exists, so two concurrent saves of the same title can never pick
    # the same free name and clobber each other ("never overwrites").
    n = 2
    target = base / f"{name}.md"
    while True:
        try:
            with open(target, "x", encoding="utf-8") as fh:
                fh.write(body)
            break
        except FileExistsError:
            target = base / f"{name} {n}.md"
            n += 1
    rel = str(target.relative_to(vault))
    engine.index(paths={rel})  # searchable immediately
    related_public = [{k: r[k] for k in ("path", "title", "sim", "near_duplicate")}
                      for r in related]
    if engine.cfg.event_log:
        detail = {"title": target.stem, "chars": len(content)}
        if related_public:
            detail["related"] = related_public
        engine.store.log_event("memory", client=client, path=rel, detail=detail)
    out = SavedMemory(rel)
    out.related = related_public
    return out


def append_to_note(engine, path: str, content: str, client: str = "") -> str:
    """Append a timestamped section to an existing note (daily logs, running
    decision records). Creates the note if it does not exist yet."""
    if not content.strip():
        raise ValueError("empty content")
    vault = engine.cfg.resolved_vault()
    rel = path if path.endswith(".md") else path + ".md"
    target = _safe_target(vault, rel)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n\n## {stamp}\n\n{content.strip()}\n"
    if target.exists():
        # appending to an existing (possibly human-authored) note — must NOT
        # mark it deletable, and must not stamp a marker into its body
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(block)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        title = target.stem
        # fresh note created by Lemory → markable for undo
        target.write_text(
            f"---\nlemory_generated: true\n---\n\n# {title}{block}", encoding="utf-8")
    rel = str(target.relative_to(vault))
    engine.index(paths={rel})
    if engine.cfg.event_log:
        engine.store.log_event("append", client=client, path=rel,
                               detail={"chars": len(content)})
    return rel


def trash_ai_note(engine, path: str, client: str = "") -> str:
    """Undo for the write path: move an AI-written note to <vault>/.trash
    (Obsidian's own trash folder, so it shows up in Obsidian's trash too).

    Guarded twice: the path must stay inside the vault, and the note's
    frontmatter must carry `lemory_generated: true` — the machine marker
    Lemory stamps on notes it CREATES (save_memory / import-chats / a hook,
    or an append that created a fresh note). Human-authored notes — including
    ones with a `source:` field, which is a common human clipping/citation
    pattern — are refused; this endpoint can never delete something the user
    wrote, and never an existing note that Lemory only appended to."""
    vault = engine.cfg.resolved_vault()
    target = _safe_target(vault, path)
    if not target.is_file():
        raise ValueError(f"no such note: {path}")
    head = target.read_text(encoding="utf-8", errors="replace")[:400]
    ai_written = False
    if head.startswith("---") and head.count("---") >= 2:
        frontmatter = head.split("---", 2)[1]
        ai_written = re.search(r"(?m)^lemory_generated:\s*true\s*$", frontmatter) is not None
    if not ai_written:
        raise ValueError(
            "refusing: not a Lemory-generated note (no 'lemory_generated: true' "
            "marker). Only notes Lemory created can be trashed here.")
    trash = vault / ".trash"
    trash.mkdir(exist_ok=True)
    dest = trash / target.name
    n = 2
    while dest.exists():
        dest = trash / f"{target.stem} {n}{target.suffix}"
        n += 1
    target.rename(dest)
    rel = str(Path(path))
    engine.index(paths={rel})  # removes it from the index
    if engine.cfg.event_log:
        engine.store.log_event("trash", client=client, path=rel)
    return str(dest.relative_to(vault))


def context_block(engine, max_chars: int = 2400) -> str:
    """Zep-style pre-assembled context: one cheap deterministic call that gives
    an agent situational awareness of the vault without a search round-trip.

    Sections (all local, no LLM): stats → recent activity → frequently
    referenced notes → most-linked hub notes → top tags."""
    store = engine.store
    lines: list[str] = []
    st = engine.status()
    lines.append(
        f"# Vault context — {Path(st['vault']).name if st['vault'] else 'unconfigured'}"
    )
    lines.append(
        f"{st['documents']} notes, {st['chunks']} chunks, {st['links']} links "
        f"(index: {st['vector_index']})"
    )

    docs = {d.id: d for d in store.all_docs()}  # reused by the hot/hub sections

    recent = store.recent_docs(days=14, limit=8)
    if recent:
        lines.append("\n## Recent notes (14d)")
        for ts, d in recent:
            lines.append(f"- {datetime.fromtimestamp(ts).date().isoformat()} · "
                         f"{d.title} ({d.path})")

    hits = store.hit_stats()
    hot = sorted(((h, did) for did, (h, _ts) in hits.items() if did in docs),
                 key=lambda x: -x[0])[:6]
    if hot:
        lines.append("\n## Frequently referenced")
        for h, did in hot:
            lines.append(f"- {docs[did].title} ({docs[did].path}) — {h}×")

    degree = store.link_degrees()
    hubs = sorted(((n, did) for did, n in degree.items() if did in docs),
                  key=lambda x: -x[0])[:6]
    if hubs:
        lines.append("\n## Hub notes (most linked)")
        for n, did in hubs:
            lines.append(f"- {docs[did].title} ({docs[did].path}) — {n} links")

    tags = store.tag_counts()[:12]  # already sorted by count
    if tags:
        lines.append("\n## Top tags")
        lines.append(", ".join(f"#{t['tag']} ({t['count']})" for t in tags))

    out = "\n".join(lines)
    return out[:max_chars]
