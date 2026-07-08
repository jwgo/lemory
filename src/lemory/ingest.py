"""Incremental vault indexing + live watcher.

The sync loop is mem0-style incremental: only notes whose content hash changed
are re-chunked/re-embedded; the embedding cache means even a full rebuild of
an unchanged vault costs zero API calls.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from .markdown import chunk_note, embed_text_for_chunk, parse_note, render_plain
from .store import Store

if TYPE_CHECKING:
    from .engine import Engine

log = logging.getLogger("lemory.ingest")


@dataclass
class SyncReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    chunks: int = 0
    embedded: int = 0  # chunks that actually hit the API (cache misses)
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def note_title(path: Path) -> str:
    return path.stem


def iter_vault_files(vault: Path, include: list[str], exclude_dirs: list[str]) -> list[Path]:
    out = []
    for pattern in include:
        for p in vault.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(vault)
            if any(part in exclude_dirs for part in rel.parts[:-1]):
                continue
            out.append(p)
    return sorted(set(out))


class Indexer:
    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.cfg = engine.cfg
        self.store: Store = engine.store

    # ------------------------------------------------------------------ sync
    def sync(self, full: bool = False, progress: Optional[Callable[[str], None]] = None) -> SyncReport:
        t0 = time.time()
        rep = SyncReport()
        vault = self.cfg.resolved_vault()
        files = iter_vault_files(vault, self.cfg.include_globs, self.cfg.exclude_dirs)
        seen_paths: set[str] = set()
        changed_docs: list[tuple[int, list[str]]] = []  # (doc_id, wikilinks)

        for f in files:
            rel = str(f.relative_to(vault))
            seen_paths.add(rel)
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                rep.errors.append(f"{rel}: {e}")
                continue
            content_hash = hashlib.sha256(raw.encode()).hexdigest()
            existing = self.store.get_doc_by_path(rel)
            if existing and existing.content_hash == content_hash and not full:
                rep.unchanged += 1
                continue

            title = note_title(f)
            note = parse_note(raw, title)
            chunks = chunk_note(
                note.body, self.cfg.chunk_chars, self.cfg.chunk_overlap,
                self.cfg.min_chunk_chars,
            )
            if not chunks:
                plain = render_plain(note.body)
                chunks = [("", plain)] if plain else [("", title)]

            embed_texts = [embed_text_for_chunk(title, h, t) for h, t in chunks]
            vectors, misses = self.engine.embed_documents_cached(embed_texts)
            rep.embedded += misses

            doc_id = self.store.store_note(
                rel, title, content_hash, f.stat().st_mtime, note.tags,
                note.frontmatter, time.time(), note.wikilinks, chunks, vectors,
            )
            changed_docs.append((doc_id, note.wikilinks))
            rep.chunks += len(chunks)
            if existing:
                rep.updated += 1
            else:
                rep.added += 1
            if progress:
                progress(f"indexed {rel} ({len(chunks)} chunks)")

        # deletions
        for doc in self.store.all_docs():
            if doc.path not in seen_paths:
                self.store.delete_document(doc.path)
                rep.removed += 1
                if progress:
                    progress(f"removed {doc.path}")

        # graph: rebuild links for changed docs. When the set of resolvable
        # titles changed (add/remove/rename/ALIAS edits), links FROM unchanged
        # docs can change too — their wikilinks/mentions may now resolve — so
        # rebuild everything. Wikilinks are persisted per doc, which makes a
        # full rebuild always correct; the title-set hash detects all cases.
        if rep.changed:
            title_hash = hashlib.sha256(
                "\n".join(sorted(self.store.title_map())).encode()
            ).hexdigest()
            titles_changed = title_hash != self.store.get_meta("title_set_hash")
            self._rebuild_links(
                changed_ids=[d for d, _ in changed_docs],
                full=bool(titles_changed or full),
            )
            self.store.set_meta("title_set_hash", title_hash)

        rep.seconds = time.time() - t0
        self.store.set_meta("last_sync", str(time.time()))
        return rep

    # ----------------------------------------------------------------- graph
    def _rebuild_links(self, changed_ids: list[int], full: bool) -> None:
        """Rebuild wiki + mention edges. `full` rebuilds every doc (needed when
        titles were added/removed); otherwise only the changed docs — safe
        because wikilinks are persisted per doc in the documents table."""
        title_to_id = self.store.title_map()
        all_wikilinks = self.store.doc_wikilinks()
        rebuild_ids = list(all_wikilinks.keys()) if full else changed_ids

        targets = self._cached_mention_targets(title_to_id) if self.cfg.mention_links else []
        for doc_id in rebuild_ids:
            merged: dict[tuple[int, str], float] = {}
            for target in all_wikilinks.get(doc_id, []):
                tid = title_to_id.get(target.strip().lower())
                if tid and tid != doc_id:
                    merged[(tid, "wiki")] = 1.0
            for dst, w in self._find_mentions(doc_id, targets).items():
                if (dst, "wiki") not in merged:
                    merged[(dst, "mention")] = w
            self.store.replace_links(doc_id, [(dst, kind, w) for (dst, kind), w in merged.items()])

    def _cached_mention_targets(self, title_to_id: dict[str, int]) -> list[tuple[re.Pattern, int]]:
        """Compiled mention regexes, cached across syncs until titles change."""
        key = hash(tuple(sorted(title_to_id.items())))
        cached = getattr(self, "_mention_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        targets = self._mention_targets(title_to_id)
        self._mention_cache = (key, targets)
        return targets

    @staticmethod
    def _mention_targets(title_to_id: dict[str, int]) -> list[tuple[re.Pattern, int]]:
        """Compile regexes for titles worth detecting as unlinked mentions."""
        out = []
        for title_lower, doc_id in title_to_id.items():
            # short/generic single words create noise ("home", "index")
            if len(title_lower) < 4:
                continue
            if " " not in title_lower and len(title_lower) < 6:
                continue
            pat = re.compile(r"(?<!\w)" + re.escape(title_lower) + r"(?!\w)", re.IGNORECASE)
            out.append((pat, doc_id))
        return out

    def _find_mentions(self, doc_id: int, targets: list[tuple[re.Pattern, int]]) -> dict[int, float]:
        c = self.store.conn()
        rows = c.execute("SELECT text FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()
        text = "\n".join(r["text"] for r in rows).lower()
        found: dict[int, float] = {}
        for pat, tid in targets:
            if tid == doc_id:
                continue
            if pat.search(text):
                found[tid] = 0.85
        return found

    # ------------------------------------------------- optional LLM enrichment
    def enrich_entities(self, max_docs: int = 50) -> int:
        """cognify-style enrichment: extract entities per note, link co-mentions.

        Optional (off by default) — the wikilink+mention graph is free, this
        spends LLM quota for extra recall on vaults with few links.
        """
        c = self.store.conn()
        rows = c.execute(
            """SELECT d.id, d.title FROM documents d
               WHERE d.id NOT IN (SELECT DISTINCT doc_id FROM entity_mentions)
               LIMIT ?""",
            (max_docs,),
        ).fetchall()
        n = 0
        for r in rows:
            chunk_rows = c.execute(
                "SELECT text FROM chunks WHERE doc_id=? ORDER BY ord LIMIT 4", (r["id"],)
            ).fetchall()
            text = "\n".join(x["text"] for x in chunk_rows)[:6000]
            try:
                data = self.engine.llm.generate_json(
                    "Extract the named entities (people, organizations, places, products, "
                    "projects, concepts) central to this note. Return JSON: "
                    '{"entities": ["..."]} with at most 12 entities.\n\n'
                    f"NOTE TITLE: {r['title']}\n\n{text}"
                )
                names = [e for e in data.get("entities", []) if isinstance(e, str)][:12]
                self.store.add_entity_mentions(r["id"], names)
                n += 1
            except Exception as e:
                log.warning("entity extraction failed for %s: %s", r["title"], e)
        if n:
            self.store.rebuild_entity_links()
        return n


# --------------------------------------------------------------------- watch
def watch(engine: "Engine", debounce: float = 2.0, on_sync: Optional[Callable] = None) -> None:
    """Block and keep the index in sync with the vault (watchdog-based)."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    vault = engine.cfg.resolved_vault()
    pending = {"dirty": False, "last": 0.0}
    # react to whatever the include globs cover, not just .md
    suffixes = {Path(g).suffix for g in engine.cfg.include_globs if Path(g).suffix} or {".md"}

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            p = str(getattr(event, "dest_path", "") or event.src_path)
            if Path(p).suffix not in suffixes:
                return
            if any(part in engine.cfg.exclude_dirs for part in Path(p).parts):
                return
            pending["dirty"] = True
            pending["last"] = time.time()

    observer = Observer()
    observer.schedule(Handler(), str(vault), recursive=True)
    observer.start()
    log.info("watching %s", vault)
    try:
        while True:
            time.sleep(0.5)
            if pending["dirty"] and time.time() - pending["last"] >= debounce:
                pending["dirty"] = False
                rep = engine.index()
                if rep.changed:
                    log.info(
                        "synced: +%d ~%d -%d (%d chunks, %.1fs)",
                        rep.added, rep.updated, rep.removed, rep.chunks, rep.seconds,
                    )
                if on_sync:
                    on_sync(rep)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
