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


def save_memory(
    engine,
    content: str,
    title: str = "",
    folder: str = "memories",
    tags: list[str] | None = None,
    source: str = "assistant",
) -> str:
    """Persist a memory as a new Markdown note. Returns the vault-relative path."""
    if not content.strip():
        raise ValueError("empty memory content")
    vault = engine.cfg.resolved_vault()
    today = datetime.now().date().isoformat()
    name = _slug(title or content.strip().splitlines()[0], f"memory {today}")
    folder = folder.strip().strip("/") or "memories"
    base = _safe_target(vault, folder)
    base.mkdir(parents=True, exist_ok=True)

    target = base / f"{name}.md"
    n = 2
    while target.exists():
        target = base / f"{name} {n}.md"
        n += 1

    tag_line = ""
    if tags:
        clean = [t.strip().lstrip("#") for t in tags if t.strip().lstrip("#")]
        if clean:
            tag_line = "tags: [" + ", ".join(clean) + "]\n"
    body = (
        f"---\ndate: {today}\nsource: {source}\n{tag_line}---\n\n"
        f"{content.strip()}\n"
    )
    target.write_text(body, encoding="utf-8")
    rel = str(target.relative_to(vault))
    engine.index(paths={rel})  # searchable immediately
    return rel


def append_to_note(engine, path: str, content: str) -> str:
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
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(block)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        title = target.stem
        target.write_text(f"# {title}{block}", encoding="utf-8")
    rel = str(target.relative_to(vault))
    engine.index(paths={rel})
    return rel


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

    docs = {d.id: d for d in store.all_docs()}
    dates = store.doc_dates()

    cutoff = time.time() - 14 * 86400
    recent = sorted(((ts, did) for did, ts in dates.items() if ts >= cutoff and did in docs),
                    key=lambda x: -x[0])[:8]
    if recent:
        lines.append("\n## Recent notes (14d)")
        for ts, did in recent:
            d = docs[did]
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
