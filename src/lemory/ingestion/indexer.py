"""Incremental vault indexing + live watcher.

The sync loop is mem0-style incremental: only notes whose content hash changed
are re-chunked/re-embedded; the embedding cache means even a full rebuild of
an unchanged vault costs zero API calls.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from .markdown import chunk_note, embed_text_for_chunk, parse_note, render_plain
from ..storage import Store

if TYPE_CHECKING:
    from ..engine import Engine

log = logging.getLogger("lemory.ingest")


@dataclass
class IndexPlan:
    """Dry-run answer to "what would indexing do, and how long will it take?"."""

    files_total: int = 0
    to_process: int = 0        # notes that would be (re)chunked
    to_remove: int = 0
    chunks_total: int = 0      # chunks across to-be-processed notes
    embeds_needed: int = 0     # chunks that would actually hit the embedder
    est_seconds: float = 0.0
    rate_chunks_per_s: float = 0.0
    rate_measured: bool = False  # False → provider default, not observed speed

    def human_eta(self) -> str:
        s = self.est_seconds
        if self.embeds_needed == 0:
            return "즉시 (임베딩 캐시 적중)"
        if s < 5:
            return "몇 초"
        if s < 90:
            return f"약 {int(round(s / 5) * 5)}초"
        if s < 5400:
            return f"약 {int(round(s / 60))}분"
        return f"약 {s / 3600:.1f}시간"


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


def active_globs(cfg) -> list[str]:
    """include_globs plus attachment types enabled in config."""
    globs = list(cfg.include_globs)
    if getattr(cfg, "index_pdf", False) and "**/*.pdf" not in globs:
        globs.append("**/*.pdf")
    return globs


def read_note_text(f: Path) -> str:
    """File → indexable text. Markdown is read verbatim; PDFs (opt-in via
    cfg.index_pdf) go through pypdf text extraction. Raises OSError on
    unreadable files so callers' existing error paths apply."""
    if f.suffix.lower() != ".pdf":
        return f.read_text(encoding="utf-8", errors="replace")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise OSError("PDF indexing requires pypdf — pip install 'lemory[pdf]'")
    try:
        reader = PdfReader(str(f))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:  # pypdf raises a zoo of types on corrupt files
        raise OSError(f"unreadable PDF: {e}")
    return "\n\n".join(pages).strip()


class Indexer:
    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.cfg = engine.cfg
        self.store: Store = engine.store

    def _chunk(self, note, title: str) -> list[tuple[str, str]]:
        """Chunk a note, with the whole-note fallback for notes that produce no
        chunks (0-byte, frontmatter-only). Shared by plan() and sync() so the
        dry-run estimate and the real sync can never disagree on chunk counts."""
        chunks = chunk_note(
            note.body, self.cfg.chunk_chars, self.cfg.chunk_overlap,
            self.cfg.min_chunk_chars,
        )
        if not chunks:
            plain = render_plain(note.body)
            chunks = [("", plain)] if plain else [("", title)]
        return chunks

    # ------------------------------------------------------------------ plan
    # provider defaults (chunks/s) used until a real rate has been observed
    _DEFAULT_RATES = {"gemini": 40.0, "openai": 40.0, "local": 20.0}

    def plan(self, full: bool = False) -> IndexPlan:
        """Estimate what sync() would do — no writes, no API calls.

        Chunks changed notes locally (fast) and checks the embedding cache to
        count real API/model work, then divides by the observed embed rate
        (persisted EMA from previous runs) or a provider default.
        """
        p = IndexPlan()
        vault = self.cfg.resolved_vault()
        files = iter_vault_files(vault, active_globs(self.cfg), self.cfg.exclude_dirs)
        p.files_total = len(files)
        seen: set[str] = set()

        keyless = self.engine.keyless
        model = dim = None
        if not keyless:
            model = self.cfg.active_embed_model()
            dim = self.cfg.active_embed_dim()
            # a pending model switch makes the next sync a full re-embed
            stored_sig = self.store.get_meta("embed_signature")
            if stored_sig is not None and stored_sig != f"{model}|{dim}" and self.store.chunk_count() > 0:
                full = True
            # keyless→keyed upgrade: the next sync full-embeds the leftover
            # NULL-vector chunks (mirrors Engine.index) — so the ETA is honest
            elif self.store.unembedded_chunk_count() > 0:
                full = True

        embed_keys: list[str] = []
        for f in files:
            rel = str(f.relative_to(vault))
            seen.add(rel)
            try:
                raw = read_note_text(f)
            except OSError:
                continue
            content_hash = hashlib.sha256(raw.encode()).hexdigest()
            existing = self.store.get_doc_by_path(rel)
            if existing and existing.content_hash == content_hash and not full:
                continue
            p.to_process += 1
            title = note_title(f)
            note = parse_note(raw, title)
            chunks = self._chunk(note, title)
            p.chunks_total += len(chunks)
            if not keyless:
                embed_keys.extend(
                    Store.cache_key(model, dim, "doc", embed_text_for_chunk(title, h, t))
                    for h, t in chunks
                )

        p.to_remove = sum(1 for d in self.store.all_docs() if d.path not in seen)
        cached = self.store.cache_get_many(embed_keys)
        p.embeds_needed = sum(1 for k in embed_keys if k not in cached)

        rate_meta = self.store.get_meta("embed_rate_ema")
        if rate_meta:
            p.rate_chunks_per_s = max(0.5, float(rate_meta))
            p.rate_measured = True
        else:
            provider = "none" if keyless else self.cfg.resolved_provider()
            p.rate_chunks_per_s = self._DEFAULT_RATES.get(provider, 20.0)
        p.est_seconds = p.embeds_needed / p.rate_chunks_per_s + p.chunks_total * 0.002 + 1.0
        return p

    # ------------------------------------------------------------------ sync
    def sync(
        self, full: bool = False, progress: Optional[Callable[[str], None]] = None,
        paths: Optional[set[str]] = None,
    ) -> SyncReport:
        """Sync the index with the vault.

        With `paths` (vault-relative), only those files are read/hashed and
        deletions are checked only among them — the fast path the watcher uses
        so one edit doesn't rescan a 10k-note vault. Without it, the full
        vault is scanned (start-up, CLI `lemory index`, safety net).
        """
        t0 = time.time()
        rep = SyncReport()
        vault = self.cfg.resolved_vault()
        targeted = paths is not None and not full
        if targeted:
            files = []
            for rel in paths:
                p = vault / rel
                if p.is_file():
                    files.append(p)
                elif self.store.get_doc_by_path(rel):
                    self.store.delete_document(rel)
                    rep.removed += 1
                    if progress:
                        progress(f"removed {rel}")
        else:
            files = iter_vault_files(vault, active_globs(self.cfg), self.cfg.exclude_dirs)
        seen_paths: set[str] = set()
        changed_docs: list[tuple[int, list[str]]] = []  # (doc_id, wikilinks)

        for f in files:
            rel = str(f.relative_to(vault))
            seen_paths.add(rel)
            try:
                raw = read_note_text(f)
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

            # privacy exclusion: `lemory: false` in frontmatter keeps a note
            # out of the index entirely — never searchable, never sent to any
            # model. If it was indexed before the flag, it is removed now.
            _priv = note.frontmatter.get("lemory")
            # accept the quoted-string forms too (lemory: "false"/no/off) so a
            # privacy opt-out never silently fails because YAML kept it a string
            if _priv is False or (isinstance(_priv, str)
                                  and _priv.strip().lower() in ("false", "no", "off")):
                if existing:
                    self.store.delete_document(rel)
                    rep.removed += 1
                    if progress:
                        progress(f"excluded (lemory: false): {rel}")
                continue  # stays in seen_paths so the delete sweep skips it

            chunks = self._chunk(note, title)

            if self.engine.keyless:
                # no embedding provider: index lexically (BM25 + link graph
                # still work); a key added later fills vectors on next sync
                vectors, misses = None, 0
            else:
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

        # deletions (targeted mode already handled its own removals above)
        if not targeted:
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

        # runs on change, and once on upgrade (pre-enrichment indexes)
        if self.cfg.stub_enrichment and (
            rep.changed or self.store.get_meta("stub_enriched") != "1"
        ):
            rep.embedded += self._enrich_stubs()
            self.store.set_meta("stub_enriched", "1")

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

    # -------------------------------------------------------- stub enrichment
    _SENT_SPLIT = re.compile(r"(?<=[.!?다요음됨])\s+|\n+")

    def _enrich_stubs(self) -> int:
        """Give stub notes an indexed representation others can find.

        A 3-line reference note is nearly invisible to BM25 and embeddings,
        yet most wikilinks in real vaults point at exactly such notes. For
        every doc whose content is shorter than cfg.stub_chars, index one
        extra pseudo-chunk: flattened frontmatter properties + the sentences
        surrounding inbound links in other notes (anchor-text style). Runs
        after every link rebuild; the embed cache absorbs unchanged contexts.
        Returns the number of enrichment chunks that hit the embedder.
        """
        import json as _json

        store = self.store
        body_len = store.doc_body_len()
        stubs = [d for d, ln in body_len.items() if ln < self.cfg.stub_chars]
        if not stubs:
            return 0
        docs = {d.id: d for d in store.all_docs()}
        c = store.conn()

        to_embed: list[tuple[int, str, str]] = []  # (doc_id, title, text)
        for doc_id in stubs:
            doc = docs.get(doc_id)
            if doc is None:
                continue
            parts: list[str] = []
            row = c.execute("SELECT frontmatter FROM documents WHERE id=?", (doc_id,)).fetchone()
            try:
                fm = _json.loads(row["frontmatter"]) if row else {}
            except _json.JSONDecodeError:
                fm = {}
            props = []
            for k, v in fm.items():
                if isinstance(v, (str, int, float)) and str(v).strip():
                    props.append(f"{k}: {v}")
                elif isinstance(v, list):
                    vals = [str(x) for x in v if isinstance(x, (str, int, float))][:6]
                    if vals:
                        props.append(f"{k}: {', '.join(vals)}")
            if props:
                parts.append(" · ".join(props[:10]))

            # backlink contexts: sentences in OTHER notes around links/mentions here
            srcs = [r["src_doc"] for r in c.execute(
                "SELECT DISTINCT src_doc FROM links WHERE dst_doc=? "
                "AND kind IN ('wiki','mention') LIMIT 6", (doc_id,))]
            tl = doc.title.lower()
            ctx: list[str] = []
            for src in srcs:
                src_doc = docs.get(src)
                if src_doc is None:
                    continue
                rows = c.execute(
                    "SELECT text FROM chunks WHERE doc_id=? AND heading != ? ORDER BY ord",
                    (src, store.ENRICH_HEADING)).fetchall()
                for r in rows:
                    for sent in self._SENT_SPLIT.split(r["text"]):
                        if tl in sent.lower() and 20 <= len(sent) <= 400:
                            ctx.append(f"({src_doc.title}) {sent.strip()}")
                            break
                    if len(ctx) and ctx[-1].startswith(f"({src_doc.title})"):
                        break
            if ctx:
                parts.append("\n".join(ctx[:6]))

            text = "\n".join(parts).strip()
            existing = c.execute(
                "SELECT text FROM chunks WHERE doc_id=? AND heading=?",
                (doc_id, store.ENRICH_HEADING)).fetchone()
            if (existing["text"] if existing else "") == text:
                continue  # unchanged — don't dirty the matrix
            to_embed.append((doc_id, doc.title, text))

        if not to_embed:
            return 0
        if self.engine.keyless:
            vectors, misses = None, 0
        else:
            embed_texts = [embed_text_for_chunk(t, "", txt) for _, t, txt in to_embed]
            vectors, misses = self.engine.embed_documents_cached(embed_texts)
        for i, (doc_id, title, text) in enumerate(to_embed):
            vec = vectors[i] if vectors is not None and text else None
            store.replace_enrichment_chunk(doc_id, title, text, vec)
        return misses

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
        # scan the note's OWN text only: enrichment pseudo-chunks quote
        # sentences from OTHER notes ("(A) ... mentions C"), and counting
        # those would give this note mention edges its author never wrote
        rows = c.execute("SELECT text FROM chunks WHERE doc_id=? AND heading != ?",
                         (doc_id, self.store.ENRICH_HEADING)).fetchall()
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
    lock = threading.Lock()
    pending: dict = {"paths": set(), "last": 0.0, "overflow": False}
    # react to whatever the include globs cover, not just .md
    suffixes = {Path(g).suffix for g in active_globs(engine.cfg) if Path(g).suffix} or {".md"}

    def note_path(p: str) -> Optional[str]:
        pp = Path(p)
        if pp.suffix not in suffixes:
            return None
        if any(part in engine.cfg.exclude_dirs for part in pp.parts):
            return None
        try:
            return str(pp.resolve().relative_to(vault))
        except ValueError:
            return None

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            with lock:
                for raw in (getattr(event, "dest_path", "") or "", event.src_path or ""):
                    rel = note_path(str(raw)) if raw else None
                    if rel:
                        pending["paths"].add(rel)
                        pending["last"] = time.time()
                if len(pending["paths"]) > 200:
                    pending["overflow"] = True  # bulk change: cheaper to full-scan

    observer = Observer()
    observer.schedule(Handler(), str(vault), recursive=True)
    observer.start()
    log.info("watching %s", vault)
    try:
        while True:
            time.sleep(0.5)
            with lock:
                ready = pending["paths"] and time.time() - pending["last"] >= debounce
                paths = set(pending["paths"]) if ready else None
                overflow = pending["overflow"]
                if ready:
                    pending["paths"].clear()
                    pending["overflow"] = False
            if not ready:
                continue
            # targeted sync for small edits; full scan for bulk changes
            rep = engine.index() if overflow else engine.index(paths=paths)
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
