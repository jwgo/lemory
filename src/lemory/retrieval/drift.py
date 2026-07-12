"""`lemory drift` — does the vault's memory still match reality?

mex (mex-memory/mex) made drift detection the headline for coding-agent
scaffolds: verify remembered paths/commands without spending tokens. The
same idea belongs to note vaults, where memory rots differently: links
break when notes are renamed, duplicate flags linger after nobody merged
them, and notes reference files that no longer exist.

All checks are deterministic reads of the existing index plus the
filesystem. Zero LLM calls. `--prompt` renders the findings as one
agent-ready repair prompt (the mex `sync` trick, vault edition).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import Engine

_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+\.md)\)")
_FM_DUP_RE = re.compile(r'(?m)^possible_duplicate_of:\s*"?\[\[([^\]]+)\]\]"?')


def detect_drift(engine: "Engine", max_per_kind: int = 50) -> dict:
    """Returns {kind: [finding, ...]} for the three vault-rot classes."""
    store = engine.store
    vault = engine.cfg.resolved_vault()
    docs = list(store.all_docs())
    titles = {d.title.lower() for d in docs}
    links_by_doc = store.doc_wikilinks()

    broken_wikilinks: list[dict] = []
    missing_files: list[dict] = []
    stale_duplicates: list[dict] = []

    for d in docs:
        if all(len(x) >= max_per_kind for x in
               (broken_wikilinks, missing_files, stale_duplicates)):
            break  # all three kinds saturated — stop scanning the rest
        raw_targets = links_by_doc.get(d.id, [])
        for target in raw_targets:
            if len(broken_wikilinks) >= max_per_kind:
                break
            t = target.split("#")[0].split("|")[0].strip()
            if not t:
                continue
            if t.lower() not in titles and (t.replace("/", "-")).lower() not in titles:
                broken_wikilinks.append({"note": d.path, "target": target})
        # md-file links live in the body and the duplicate flag in the
        # frontmatter (stripped from chunks), so this one class of check still
        # needs the raw file — but the early-exit above means a saturated run
        # stops re-reading the rest of the vault
        try:
            raw = (vault / d.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _MD_LINK_RE.finditer(raw):
            if len(missing_files) >= max_per_kind:
                break
            rel = m.group(1)
            if rel.startswith(("http://", "https://")):
                continue
            if not (vault / d.path).parent.joinpath(rel).exists() \
                    and not (vault / rel).exists():
                missing_files.append({"note": d.path, "target": rel})
        dm = _FM_DUP_RE.search(raw[:600])
        if dm and len(stale_duplicates) < max_per_kind:
            other = dm.group(1)
            if other.lower() in titles:
                stale_duplicates.append({"note": d.path, "duplicate_of": other})

    return {
        "broken_wikilinks": broken_wikilinks[:max_per_kind],
        "missing_file_links": missing_files[:max_per_kind],
        "unresolved_duplicates": stale_duplicates[:max_per_kind],
        "notes_scanned": len(docs),
    }


def render_repair_prompt(findings: dict, vault: str) -> str:
    """One agent-ready prompt that repairs exactly what drifted."""
    parts = [
        f"The Obsidian vault at {vault} has drifted. Repair ONLY the items "
        "below; do not touch anything else.\n",
    ]
    if findings["broken_wikilinks"]:
        parts.append("## Broken [[wikilinks]] (target note does not exist)")
        for f in findings["broken_wikilinks"]:
            parts.append(f"- in `{f['note']}`: [[{f['target']}]] "
                         "(fix the link if the note was renamed, or remove it)")
    if findings["missing_file_links"]:
        parts.append("\n## Markdown links to files that do not exist")
        for f in findings["missing_file_links"]:
            parts.append(f"- in `{f['note']}`: ({f['target']})")
    if findings["unresolved_duplicates"]:
        parts.append("\n## Memories still flagged as possible duplicates")
        for f in findings["unresolved_duplicates"]:
            parts.append(
                f"- `{f['note']}` is flagged possible_duplicate_of "
                f"[[{f['duplicate_of']}]]: merge them (keep the older note, "
                "append any new facts, delete the flag) or remove the flag "
                "if they are genuinely different.")
    if len(parts) == 1:
        return "No drift detected. The vault's memory matches reality."
    parts.append("\nAfter repairing, run `lemory index` to refresh the index.")
    return "\n".join(parts)
